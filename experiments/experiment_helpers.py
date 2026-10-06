"""
Helper functions for running experiments from both CLI and UI.
"""
import os
import csv
from typing import List, Dict, Any, Optional
from galileo.experiments import run_experiment
from galileo.datasets import get_dataset, create_dataset, list_datasets
from galileo.schema.metrics import GalileoMetrics
from galileo import galileo_context
from galileo import ConflictError
from galileo.handlers.langchain import GalileoCallback
from domain_manager import DomainManager
from setup_env import get_domain_project_name
from helpers.galileo_api_helpers import get_galileo_app_url


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
    """Get the standardized dataset name for a domain."""
    return f"{domain_name.title()} Domain Dataset"


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
        
    Returns:
        Experiment results
    """
    if metrics is None:
        metrics = DEFAULT_METRICS
    
    if project is None:
        cfg = DomainManager().load_domain_config(domain_name)
        project = get_domain_project_name(domain_name, cfg.config)
    
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
        project=project
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
