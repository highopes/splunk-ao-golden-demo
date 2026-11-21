"""
Environment Setup - Load secrets and set environment variables
"""
import os
import warnings
import toml
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

# Silence Galileo SDK span-serialization noise. The Galileo ingestion models
# subclass the core span types and hold child spans in a discriminated union,
# which makes Pydantic 2.12 emit "PydanticSerializationUnexpectedValue" /
# "Pydantic serializer warnings" (field_name='spans') on every trace upload.
# It's cosmetic — traces still serialize and upload correctly, and it's provider
# independent (not related to Ollama/OpenAI/Bedrock). Registered here (imported
# before `galileo`) so it applies process-wide. Remove this filter if it ever
# masks a real serialization problem.
warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
    category=UserWarning,
    module="pydantic",
)


SPLUNKSE_CONSOLE_URL = "https://console.multitenant.galileocloud.io"


@dataclass(frozen=True)
class BackendProfile:
    """How the app reaches one kind of Splunk AO backend.

    splunkse: the SaaS tenant. Agent Control and REST helpers go through the
    Console's UI proxy, the header name is fixed, and the Console has a tenant
    login path (/splunkse).
    imlab-onprem: a self-hosted Splunk AO On-prem. Agent Control and REST go
    to the API host (or explicit in-cluster service URLs) and the Console has
    no tenant path. No environment-specific address is hard-coded here: the
    Console URL always comes from secrets.toml.
    """

    name: str
    default_console_url: str
    agent_control_via_console: bool
    rest_via_console: bool
    allowed_control_headers: Tuple[str, ...]
    default_control_header: str
    console_tenant_path: str
    # Experiment scorers used when a domain does not list its own; GalileoMetrics names.
    experiment_metrics: Tuple[str, ...]
    prefer_luna_metrics: bool


BACKEND_PROFILES: Dict[str, BackendProfile] = {
    "splunkse": BackendProfile(
        name="splunkse",
        default_console_url=SPLUNKSE_CONSOLE_URL,
        agent_control_via_console=True,
        rest_via_console=True,
        allowed_control_headers=("Galileo-API-Key",),
        default_control_header="Galileo-API-Key",
        console_tenant_path="/splunkse",
        experiment_metrics=("ground_truth_adherence", "prompt_injection", "context_adherence"),
        prefer_luna_metrics=False,
    ),
    "imlab-onprem": BackendProfile(
        name="imlab-onprem",
        default_console_url="",
        agent_control_via_console=False,
        rest_via_console=False,
        allowed_control_headers=("Splunk-AO-API-Key", "Galileo-API-Key"),
        default_control_header="Splunk-AO-API-Key",
        console_tenant_path="",
        # Luna (SLM) scorers run on the local Wizard; Ground Truth Adherence has
        # no Luna variant and uses the platform's LLM judge.
        experiment_metrics=(
            "ground_truth_adherence",
            "context_adherence_luna",
            "prompt_injection_luna",
            "completeness_luna",
        ),
        prefer_luna_metrics=True,
    ),
}
DEFAULT_BACKEND_PROFILE = "splunkse"


class BackendConfigError(ValueError):
    """Configuration error whose message never contains secret values."""


def get_backend_profile(name: Optional[str] = None) -> BackendProfile:
    """Return a registered profile; ``None`` uses DEMO_BACKEND_PROFILE or splunkse."""
    resolved = str(name or os.environ.get("DEMO_BACKEND_PROFILE") or DEFAULT_BACKEND_PROFILE).strip()
    profile = BACKEND_PROFILES.get(resolved)
    if profile is None:
        # The profile name is a label, never a credential.
        raise BackendConfigError(
            f"Unknown backend_profile '{resolved}'; expected one of: {', '.join(BACKEND_PROFILES)}"
        )
    return profile


def _derive_galileo_api_url(console_url: str, explicit_url: str = "") -> str:
    """Derive Galileo API URL from console URL when not set explicitly."""
    if explicit_url:
        return explicit_url.rstrip("/")
    console_url = (console_url or "").rstrip("/")
    if not console_url:
        return ""
    if "console." in console_url:
        return console_url.replace("console.", "api.", 1)
    return ""


def _derive_agent_control_url(console_url: str, explicit_url: str = "", *, api_url: str = "", via_console: bool = True) -> str:
    """Derive the Agent Control base URL.

    splunkse uses the Console UI proxy (<console>/api/agent-control); on-prem
    uses the API ingress prefix (<api>/agent-control).
    """
    if explicit_url:
        return explicit_url.rstrip("/")
    if not via_console:
        api_url = (api_url or "").rstrip("/")
        return f"{api_url}/agent-control" if api_url else ""
    console_url = (console_url or "").rstrip("/")
    if not console_url:
        return ""
    return f"{console_url}/api/agent-control"


def resolve_backend_settings(secrets: Mapping) -> Dict[str, str]:
    """Resolve every backend address and header from one secrets mapping.

    Explicit ``galileo_api_url`` / ``galileo_ingest_url`` / ``agent_control_url``
    win over derived values (in-cluster service addresses). ``galileo_console_url``
    is only used for links opened by the presenter's browser and, for splunkse,
    for the Console UI proxy. Raises ValueError without echoing any value.
    """
    profile = get_backend_profile(secrets.get("backend_profile") or DEFAULT_BACKEND_PROFILE)
    console_url = str(secrets.get("galileo_console_url") or profile.default_console_url).rstrip("/")
    if not console_url:
        raise BackendConfigError(f"backend_profile {profile.name} requires galileo_console_url")
    api_url = _derive_galileo_api_url(console_url, str(secrets.get("galileo_api_url") or ""))
    if not api_url:
        raise BackendConfigError("galileo_api_url could not be derived; set it explicitly")
    agent_control_url = _derive_agent_control_url(
        console_url,
        str(secrets.get("agent_control_url") or ""),
        api_url=api_url,
        via_console=profile.agent_control_via_console,
    )
    control_header = str(secrets.get("agent_control_api_key_header") or profile.default_control_header)
    if control_header not in profile.allowed_control_headers:
        raise BackendConfigError(
            f"{profile.name} requires agent_control_api_key_header to be one of "
            f"{', '.join(profile.allowed_control_headers)} (a header name, not a credential)"
        )
    rest_base_url = f"{console_url}/api/galileo" if profile.rest_via_console else api_url
    return {
        "profile": profile.name,
        "console_url": console_url,
        "api_url": api_url,
        "ingest_url": str(secrets.get("galileo_ingest_url") or "").rstrip("/"),
        "agent_control_url": agent_control_url,
        "control_header": control_header,
        "demo_console_url": str(
            secrets.get("demo_console_url") or f"{console_url}{profile.console_tenant_path}"
        ).rstrip("/"),
        "rest_base_url": rest_base_url,
    }


def get_domain_project_name(domain_name: str, domain_config: Optional[dict] = None) -> str:
    """
    Get the Galileo project name for a domain.
    
    Priority:
    1. If domain_config has a 'galileo.project' field, use that (explicit)
    2. Otherwise, use default: "galileo-demo-{domain_name}"
    
    Args:
        domain_name: Name of the domain (e.g., "finance")
        domain_config: Loaded domain config dict (optional, for explicit project name)
    
    Returns:
        Project name for the domain
    """
    # Check if domain config explicitly specifies a project
    if domain_config and "galileo" in domain_config and "project" in domain_config["galileo"]:
        return domain_config["galileo"]["project"]
    
    # Default convention: galileo-demo-{domain_name}
    return f"galileo-demo-{domain_name}"


def setup_environment(domain_name: Optional[str] = None, domain_config: Optional[dict] = None):
    """
    Load secrets from .streamlit/secrets.toml and set environment variables.
    
    If domain_name is provided:
        - Sets domain-specific GALILEO_PROJECT (from config or default)
        - Sets domain-specific GALILEO_LOG_STREAM (from config or default)
    
    If domain_name is None (for CLI scripts):
        - Only sets API keys and non-domain-specific settings
        - Project name should be set by the calling script after loading domain config
    
    Args:
        domain_name: Name of the domain to set up (e.g., "finance"). Optional for CLI scripts.
        domain_config: Loaded domain config dict (optional, for domain-specific settings)
    """
    secrets_path = Path(__file__).resolve().parent / ".streamlit/secrets.toml"
    
    if not secrets_path.exists():
        print("⚠️  .streamlit/secrets.toml not found. Please create it with your API keys.")

        return
    
    try:
        # Load secrets
        secrets = toml.load(secrets_path)

        backend = resolve_backend_settings(secrets)
        console_url = backend["console_url"]
        galileo_api_url = backend["api_url"]
        agent_control_url = backend["agent_control_url"]
        galileo_api_key = secrets.get("galileo_api_key", "")
        control_header = backend["control_header"]
        
        # Base environment variables (always set)
        env_vars = {
            # No default: an unset ollama_base_url means "Local not configured".
            # Connections still fall back to localhost via get_ollama_base_url().
            "OLLAMA_BASE_URL": secrets.get("ollama_base_url", ""),
            "OLLAMA_DEFAULT_CHAT_MODEL": secrets.get(
                "ollama_default_chat_model", "gemma4"
            ),
            "OLLAMA_EMBEDDING_MODEL": secrets.get(
                "ollama_embedding_model", "nomic-embed-text"
            ),
            "OPENAI_API_KEY": secrets.get("openai_api_key", ""),
            "OPENAI_DEFAULT_CHAT_MODEL": secrets.get(
                "openai_default_chat_model", "gpt-5.4-nano"
            ),
            "OPENAI_EMBEDDING_MODEL": secrets.get(
                "openai_embedding_model", "text-embedding-3-large"
            ),
            "OPENAI_EMBEDDING_DIMENSIONS": str(
                secrets.get("openai_embedding_dimensions", 768)
            ),
            "AWS_BEARER_TOKEN_BEDROCK": secrets.get("bedrock_api_key", ""),
            "AWS_REGION": secrets.get("aws_region", "us-east-1"),
            "BEDROCK_DEFAULT_CHAT_MODEL": secrets.get(
                "bedrock_default_chat_model", "mistral.ministral-3-14b-instruct"
            ),
            "BEDROCK_EMBEDDING_MODEL": secrets.get(
                "bedrock_embedding_model", "amazon.titan-embed-text-v2:0"
            ),
            # Optional OpenAI-compatible vLLM chat server (e.g. Qwen3 in-cluster).
            "VLLM_BASE_URL": secrets.get("vllm_base_url", ""),
            "VLLM_DEFAULT_CHAT_MODEL": secrets.get("vllm_default_chat_model", ""),
            "VLLM_API_KEY": secrets.get("vllm_api_key", ""),
            "DEMO_BACKEND_PROFILE": backend["profile"],
            "GALILEO_API_KEY": galileo_api_key,
            "GALILEO_API_URL": galileo_api_url,
            "GALILEO_INGEST_URL": backend["ingest_url"],
            "GALILEO_REST_BASE_URL": backend["rest_base_url"],
            "GALILEO_CONSOLE_URL": console_url,
            "DEMO_CONSOLE_URL": backend["demo_console_url"],
            "AGENT_CONTROL_URL": agent_control_url,
            "AGENT_CONTROL_API_KEY": galileo_api_key,
            "AGENT_CONTROL_AGENT_NAME": secrets.get("agent_control_agent_name", ""),
            "AGENT_CONTROL_API_KEY_HEADER": control_header,
            "AGENT_CONTROL_RUNTIME_AUTH_MODE": secrets.get("agent_control_runtime_auth_mode", "jwt"),
            "AGENT_CONTROL_TARGET_TYPE": secrets.get("agent_control_target_type", "log_stream"),
            "ADMIN_KEY": secrets.get("admin_key", ""),
            "POSTGRES_HOST": secrets.get("postgres_host", "localhost"),
            "POSTGRES_PORT": secrets.get("postgres_port", "5432"),
            "POSTGRES_USER": secrets.get("postgres_user", "postgres"),
            "POSTGRES_PASSWORD": secrets.get("postgres_password", ""),
            "POSTGRES_DB": secrets.get("postgres_db", "vectordb"),
            "ENVIRONMENT": secrets.get("environment", "local")
        }
        
        # If domain is specified, add domain-specific settings
        if domain_name:
            project_name = get_domain_project_name(domain_name, domain_config)
            log_stream = "default"
            if domain_config and "galileo" in domain_config and "log_stream" in domain_config["galileo"]:
                log_stream = domain_config["galileo"]["log_stream"]
            
            env_vars["GALILEO_PROJECT"] = project_name
            env_vars["GALILEO_LOG_STREAM"] = log_stream
        
        # Provider credentials must reflect secrets.toml exactly. If a value is
        # empty, clear any ambient/leftover env var (exported in the shell, or
        # set by a previous run) so a provider can't appear "configured" — and
        # thus selectable in the UI — just because the variable exists in the
        # environment. Other empty keys are left as-is (only warned about).
        _AUTHORITATIVE_KEYS = {
            "OLLAMA_BASE_URL",
            "OPENAI_API_KEY",
            "AWS_BEARER_TOKEN_BEDROCK",
            "VLLM_BASE_URL",
            "VLLM_API_KEY",
            # Optional addresses: a stale value from another profile must not linger.
            "GALILEO_INGEST_URL",
        }
        _OPTIONAL_KEYS = {"VLLM_DEFAULT_CHAT_MODEL"}
        for key, value in env_vars.items():
            if value:  # Only set if value is not empty
                os.environ[key] = value
                # print(f"✅ Set {key}")
            elif key in _AUTHORITATIVE_KEYS:
                os.environ.pop(key, None)
                if key not in {"GALILEO_INGEST_URL", "VLLM_API_KEY"}:
                    print(f"ℹ️  {key} not configured in secrets.toml (cleared)")
            elif key not in _OPTIONAL_KEYS:
                print(f"⚠️  {key} not set (empty value)")

        # Optional dedicated ingest-service URL (in-cluster). Unset keeps the
        # SDK default (probe and native ingest on GALILEO_API_URL).
        from helpers.galileo_ingest import configure_ingest_url
        configure_ingest_url(backend["ingest_url"])

        # Optional: pin RAG embeddings to one backend regardless of the chat
        # provider toggle. Left unset by default so embeddings follow the UI
        # selection (each provider has its own prebuilt pgvector index).
        embedding_provider = secrets.get("embedding_provider", "")
        if embedding_provider:
            os.environ["EMBEDDING_PROVIDER"] = embedding_provider
        else:
            os.environ.pop("EMBEDDING_PROVIDER", None)

        if domain_name:
            project_name = get_domain_project_name(domain_name, domain_config)
            print(f"🔧 Environment setup complete for domain: {domain_name} (project: {project_name})")
        else:
            print("🔧 Environment setup complete (domain-agnostic mode)")
        
    except BackendConfigError as e:
        raise ValueError(f"Invalid secrets configuration: {e}") from None
    except Exception as e:
        # Do not include TOML parse errors: they can contain a secret line.
        # Frame locations (file:line function) never contain values.
        import sys
        import traceback

        for frame in traceback.extract_tb(e.__traceback__)[-6:]:
            print(f"   at {Path(frame.filename).name}:{frame.lineno} {frame.name}", file=sys.stderr)
        raise ValueError(
            f"Invalid secrets configuration ({type(e).__name__}); check the local TOML file and backend_profile"
        ) from None


if __name__ == "__main__":
    setup_environment()
