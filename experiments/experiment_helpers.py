"""
Helper functions for running experiments from both CLI and UI.
"""
import os
import csv
import hashlib
import json
from typing import List, Dict, Any, Iterable, Optional, Tuple
from galileo.experiments import run_experiment
from galileo.datasets import get_dataset, create_dataset, list_datasets
from galileo.schema.metrics import GalileoMetrics
from galileo import galileo_context
from galileo import ConflictError
from galileo.handlers.langchain import GalileoCallback
from domain_manager import DomainManager
from setup_env import get_domain_project_name
from helpers.galileo_api_helpers import get_galileo_app_url
from helpers.galileo_compat import tolerate_unknown_permission_actions
from helpers.galileo_ingest import apply_domain_reliable_ingest, reliable_ingest_requested
from helpers.llm_utils import describe_model_runtime, get_model_runtime_options

# The tenant can return Project permission actions newer than the SDK enums.
tolerate_unknown_permission_actions()

# Default metrics for experiments
DEFAULT_METRICS = [
    GalileoMetrics.ground_truth_adherence,
    GalileoMetrics.prompt_injection,
    GalileoMetrics.context_adherence
]

# These native scorers were read back from splunkse. The upstream Chunk
# Attribution Utilization scorer is not available in this tenant.
AVAILABLE_METRICS = {
    metric.value: metric for metric in DEFAULT_METRICS
}


def read_dataset_csv(dataset_file: str) -> List[Dict[str, str]]:
    """
    Read a CSV file and return list of input/output pairs.
    
    Args:
        dataset_file: Path to the CSV file
        
    Returns:
        List of dictionaries with 'input' and 'output' keys
    """
    dataset = []
    with open(dataset_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        if not {"input", "output"}.issubset(reader.fieldnames or []):
            raise ValueError("Dataset CSV requires input and output columns")
        for row in reader:
            if not str(row.get('input') or '').strip() or not str(row.get('output') or '').strip():
                raise ValueError(f"Dataset row {reader.line_num} requires non-empty input and output")
            dataset.append({'input': row['input'].strip(), 'output': row['output'].strip()})
    return dataset


def scenario_key(scenario_input: str) -> str:
    """Stable per-question key: first 16 hex chars of sha256(trimmed input)."""
    return hashlib.sha256(str(scenario_input or "").strip().encode("utf-8")).hexdigest()[:16]


def dataset_content_hash(records: Iterable[Tuple[str, str]]) -> str:
    """Order-independent sha256 over trimmed (input, ground truth) pairs."""
    canonical = sorted([str(i or "").strip(), str(o or "").strip()] for i, o in records)
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def local_dataset_records(dataset_file: str) -> List[Tuple[str, str]]:
    """Return (input, ground truth) pairs from a local dataset CSV."""
    return [(row["input"], row["output"]) for row in read_dataset_csv(dataset_file)]


def remote_dataset_records(dataset: Any) -> List[Tuple[str, str]]:
    """Read (input, ground truth) pairs back from a Splunk AO dataset (read-only)."""
    content = dataset.get_content()
    rows = getattr(content, "rows", None) if content is not None else None
    if not rows or not isinstance(rows, list):
        raise ValueError("Dataset content could not be read back from Splunk AO")
    records = []
    for row in rows:
        values = row.values_dict.to_dict()
        ground_truth = values.get("ground_truth", values.get("output"))
        records.append((str(values.get("input") or ""), str(ground_truth or "")))
    return records


def experiment_runtime_tags(
    domain_config: dict, model_name: Optional[str], llm_provider: str
) -> Dict[str, str]:
    """Experiment tags describing the explicit application-model runtime settings."""
    model_cfg = domain_config.get("model", {})
    model = model_name or {
        "hosted": model_cfg.get("hosted_default_model"),
        "bedrock": model_cfg.get("bedrock_default_model"),
    }.get(llm_provider) or model_cfg.get("default_model")
    options = get_model_runtime_options(model_cfg, model, llm_provider)
    return {k: str(v) for k, v in describe_model_runtime(model, llm_provider, options).items()}


def code_version() -> str:
    """Short git commit of this checkout, with ``-dirty`` for local changes; "unknown" without git."""
    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], cwd=root,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"
    return f"{commit}-dirty" if dirty else commit


def chaos_state() -> str:
    """Comma-separated enabled chaos modes for the current UI session/process, or "off"."""
    from chaos_engine import get_chaos_engine

    chaos = get_chaos_engine()
    modes = {
        "tool_instability": chaos.tool_instability_enabled,
        "sloppiness": chaos.sloppiness_enabled,
        "rag": chaos.rag_chaos_enabled,
        "rate_limit": chaos.rate_limit_chaos_enabled,
        "data_corruption": chaos.data_corruption_enabled,
    }
    enabled = [name for name, on in modes.items() if on]
    return ",".join(enabled) if enabled else "off"


def create_domain_dataset(domain_name: str, dataset_file: str, custom_name: Optional[str] = None) -> Any:
    """
    Create a Galileo dataset from a domain's CSV file.
    
    Args:
        domain_name: Name of the domain
        dataset_file: Path to the dataset CSV file
        custom_name: Optional custom name for the dataset (defaults to domain dataset name)
        
    Returns:
        Created dataset object
    """
    dataset_content = read_dataset_csv(dataset_file)
    
    if not dataset_content:
        raise ValueError("No data found in dataset file")

    config = DomainManager().load_domain_config(domain_name)
    project = get_domain_project_name(domain_name, config.config)
    dataset_name = custom_name if custom_name else get_domain_dataset_name(domain_name)
    try:
        dataset = create_dataset(name=dataset_name, content=dataset_content, project_name=project)
    except ConflictError:
        dataset = get_dataset(name=dataset_name, project_name=project)
        if dataset is None:
            raise ValueError("Conflicting dataset could not be resolved")
    return dataset


def get_domain_dataset_name(domain_name: str) -> str:
    """Get the dataset name for a domain (``experiments.dataset_name`` when configured)."""
    try:
        configured = (
            DomainManager().load_domain_config(domain_name).config.get("experiments") or {}
        ).get("dataset_name")
    except Exception:
        configured = None
    return str(configured).strip() if configured else f"{domain_name.title()} Domain Dataset"


def get_dataset_by_name(name: str) -> Any:
    """
    Get a dataset by name.
    
    Args:
        name: Dataset name
        
    Returns:
        Dataset object
    """
    return get_dataset(name=name)


def get_dataset_by_id(dataset_id: str) -> Any:
    """
    Get a dataset by ID.
    
    Args:
        dataset_id: Dataset ID
        
    Returns:
        Dataset object
    """
    return get_dataset(id=dataset_id)


def get_all_datasets() -> List[Any]:
    """
    Get all available datasets.
    
    Returns:
        List of dataset objects
    """
    return list_datasets()


def create_experiment_function(
    domain_name: str,
    agent_factory,
    model_name: Optional[str] = None,
    llm_provider: str = "local",
):
    """
    Create a function that can be used in experiments.
    This function will use the existing agent from AgentFactory.
    
    Args:
        domain_name: Name of the domain
        agent_factory: AgentFactory instance
        model_name: Optional model override (e.g. from UI selector); uses domain default if None
        
    Returns:
        Function that can be called for each experiment row
    """
    def experiment_function(input_data):
        """
        Function that will be called for each row in the dataset.
        This uses the existing agent infrastructure.
        """
        # Get the current logger to check if we're in an experiment
        galileo_logger = galileo_context.get_logger_instance()
        is_in_experiment = galileo_logger.current_parent() is not None
        
        # Create the agent using the existing factory (with optional model override)
        agent = agent_factory.create_agent(
            domain_name,
            "LangGraph",
            model_name=model_name,
            llm_provider=llm_provider,
            galileo_logger=galileo_logger,
        )
        # The experiment SDK owns the sample trace. Do not conclude/flush it
        # inside the agent, and route manually logged retrieval to this logger.
        agent.manage_trace_lifecycle = not is_in_experiment
        
        # Override the agent's config to use the proper callback for experiments
        if is_in_experiment:
            # Create callback that doesn't start/flush traces when in experiment
            galileo_callback = GalileoCallback(
                galileo_logger,
                start_new_trace=False,
                flush_on_chain_end=False
            )
            agent.config = {
                "configurable": {"thread_id": agent.session_id}, 
                "callbacks": [galileo_callback]
            }
        
        # Get the input from the dataset row
        # Handle both string inputs and dictionary inputs
        if isinstance(input_data, str):
            user_input = input_data
        else:
            user_input = input_data.get('input', '')
        
        # Run the agent with the input
        # The agent will handle logging automatically
        messages = [{"role": "user", "content": user_input}]
        response = agent.process_query(messages)
        
        return response
    
    return experiment_function


def run_domain_experiment(
    domain_name: str,
    experiment_name: str,
    dataset: Any,
    agent_factory,
    metrics: Optional[List] = None,
    project: Optional[str] = None,
    model_name: Optional[str] = None,
    llm_provider: str = "local",
    experiment_group: Optional[str] = None,
    experiment_tags: Optional[Dict[str, str]] = None,
) -> Any:
    """
    Run an experiment for a domain.
    
    Args:
        domain_name: Name of the domain
        experiment_name: Name for the experiment
        dataset: Dataset object to use
        agent_factory: AgentFactory instance
        metrics: List of metrics to evaluate (defaults to DEFAULT_METRICS)
        project: Galileo project name (defaults to GALILEO_PROJECT env var)
        model_name: Optional model override (e.g. from UI); uses domain default if None
        experiment_group: Optional Experiment Group name; defaults to the domain's
            ``experiments.group`` when configured, otherwise the SDK/API default.
        experiment_tags: Optional extra experiment tags (string values).
        
    Returns:
        Experiment results
    """
    if metrics is None:
        metrics = DEFAULT_METRICS
    
    cfg = DomainManager().load_domain_config(domain_name)
    if project is None:
        project = get_domain_project_name(domain_name, cfg.config)

    domain_experiments = cfg.config.get("experiments") or {}
    domain_group = domain_experiments.get("group")
    group = experiment_group or domain_group
    tags: Dict[str, str] = {}
    if domain_group:
        # Domains with a dedicated Experiment Group record the application model
        # runtime, dataset lineage, code version and chaos state so UI and CLI
        # runs stay comparable (and incomparable runs are detectable on export).
        tags.update(experiment_runtime_tags(cfg.config, model_name, llm_provider))
        tags["dataset_hash"] = dataset_content_hash(remote_dataset_records(dataset))
        if domain_experiments.get("dataset_version"):
            tags["dataset_version"] = str(domain_experiments["dataset_version"])
        tags["code_version"] = code_version()
        tags["chaos_state"] = chaos_state()
    if experiment_tags:
        tags.update({str(k): str(v) for k, v in experiment_tags.items()})
    run_kwargs: Dict[str, Any] = {}
    if group:
        run_kwargs["experiment_group"] = group
    if tags:
        run_kwargs["experiment_tags"] = tags
    
    if reliable_ingest_requested(cfg.config):
        # Experiment traces are flushed by the SDK's batch logger; opted-in
        # domains need reliable=True so the platform prices LLM spans.
        from galileo.projects import create_project, get_project

        galileo_project = get_project(name=project) or create_project(project)
        apply_domain_reliable_ingest(cfg.config, getattr(galileo_project, "id", None))

    # Create the experiment function (with optional model override)
    experiment_function = create_experiment_function(
        domain_name,
        agent_factory,
        model_name=model_name,
        llm_provider=llm_provider,
    )
    
    # Run the experiment
    results = run_experiment(
        experiment_name,
        dataset=dataset,
        function=experiment_function,
        metrics=metrics,
        project=project,
        **run_kwargs,
    )

    # Current splunkse Console routes runs under their experiment group. The
    # SDK's legacy /experiments/{run_id} link opens an empty group page.
    if isinstance(results, dict) and results.get("experiment") is not None:
        experiment = results["experiment"]
        base = f"{get_galileo_app_url()}/project/{experiment.project_id}/experiments"
        group_id = getattr(experiment, "experiment_group_id", None)
        results["link"] = (
            f"{base}/{group_id}/{experiment.id}"
            if isinstance(group_id, str) and group_id else base
        )
    
    return results
