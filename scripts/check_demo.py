#!/usr/bin/env python3
"""Read-only preflight. Never prints credentials; cloud checks are opt-in.

Checks follow backend_profile (splunkse / imlab-onprem). --in-cluster is for the
Kubernetes Pod: it checks this Pod's Streamlit health endpoint and the merged CA
bundle instead of a local 127.0.0.1:8501 session, and with --live also probes
the in-cluster AO service addresses with TLS verification.
"""
import argparse
import importlib.metadata
import os
from pathlib import Path
import socket
import ssl
import sys
import tomllib
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="healthcare")
    parser.add_argument("--live", action="store_true", help="Read cloud project/stream and request a small LLM completion")
    parser.add_argument("--in-cluster", action="store_true", help="Run inside the Kubernetes Pod (Pod health, CA bundle, internal AO addresses)")
    args = parser.parse_args()
    failures = []

    def check(label, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'}  {label}{': ' + detail if detail else ''}")
        if not ok:
            failures.append(label)

    check("Python", sys.version_info >= (3, 11), sys.version.split()[0])
    for package in ("streamlit", "langgraph", "langchain-core", "langchain-postgres", "galileo", "agent-control-sdk", "psycopg"):
        try:
            check(package, True, importlib.metadata.version(package))
        except importlib.metadata.PackageNotFoundError:
            check(package, False, "not installed")
    path = ROOT / ".streamlit/secrets.toml"
    if not path.exists():
        check("secrets.toml", False, "copy the example and edit locally")
        return 1
    try:
        with path.open("rb") as handle:
            secrets = tomllib.load(handle)
    except Exception:
        check("secrets.toml", False, "invalid TOML (contents suppressed)")
        return 1
    from setup_env import resolve_backend_settings
    try:
        backend = resolve_backend_settings(secrets)
    except ValueError as exc:
        check("backend_profile", False, str(exc))
        return 1
    profile = backend["profile"]
    check("backend_profile", True, profile)
    if profile == "splunkse":
        check("SDK Console base URL", backend["console_url"] == "https://console.multitenant.galileocloud.io")
        check("SDK API base URL (explicit or derived)", backend["api_url"] == "https://api.multitenant.galileocloud.io")
        check("Control URL (explicit or derived)", backend["agent_control_url"] == "https://console.multitenant.galileocloud.io/api/agent-control")
        check("splunkse Console entry", backend["demo_console_url"] == "https://console.multitenant.galileocloud.io/splunkse")
        check("Control authentication header name", backend["control_header"] == "Galileo-API-Key")
    else:
        # On-prem addresses are environment-specific; check shape, not values.
        check("Console URL (browser links)", backend["console_url"].startswith("https://"))
        check("SDK API base URL (explicit or derived)", backend["api_url"].startswith("https://"))
        check("Control URL (explicit or derived)", backend["agent_control_url"].startswith(("https://", "http://")))
        check("Control authentication header name", True, backend["control_header"])
        if backend["ingest_url"]:
            check("Ingest URL (explicit)", backend["ingest_url"].startswith("https://"))
        if args.in_cluster:
            check("REST helpers bypass the Console", backend["rest_base_url"] == backend["api_url"])
    for key in ("galileo_api_key", "openai_api_key", "postgres_password", "agent_control_agent_name"):
        val = str(secrets.get(key, "")).strip()
        check(key, bool(val) and not val.startswith("YOUR_") and val != "...")
    try:
        from domain_manager import DomainManager
        from setup_env import setup_environment
        os.chdir(ROOT)
        domain = DomainManager().load_domain_config(args.domain)
        setup_environment(args.domain, domain.config)
        check("Domain", True, args.domain)
        from helpers.pgvector_utils import get_postgres_connection_string, get_collection_name
        from sqlalchemy import create_engine, text
        engine = create_engine(get_postgres_connection_string(), connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            vector = conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar()
            check("pgvector", bool(vector), str(vector or "missing extension"))
            docs = ROOT / domain.docs_dir
            from helpers.sql_utils import relational_table_name, parse_relational_csv_name
            for csv_file in sorted(docs.glob("relational_*.csv")):
                table = relational_table_name(args.domain, parse_relational_csv_name(csv_file))
                count = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
                check(table, count > 0, f"{count} rows")
            collection = get_collection_name(args.domain, "hosted")
            count = conn.execute(text("SELECT COUNT(*) FROM langchain_pg_embedding e JOIN langchain_pg_collection c ON e.collection_id=c.uuid WHERE c.name=:name"), {"name": collection}).scalar()
            check(collection, count > 0, f"{count} documents")
        engine.dispose()
        vectorstore_cfg = domain.config.get("vectorstore", {})
        if vectorstore_cfg.get("strict_index"):
            from helpers.pgvector_utils import verify_strict_index
            try:
                info = verify_strict_index(args.domain, vectorstore_cfg)
                check("Strict index metadata", True, ", ".join(f"{k}={v}" for k, v in info.items()))
            except Exception as exc:
                check("Strict index metadata", False, str(exc))
    except Exception as exc:
        name = type(exc).__name__
        hint = {
            "OperationalError": "database unreachable; run scripts/db.py start (scripts/start-demo.sh does this automatically)",
            "ProgrammingError": f"tables/index missing; run helpers/setup_vectordb.py {args.domain}",
        }.get(name, "start DB and load domain data")
        check("Database / domain data", False, f"{name}; {hint}")
    if args.in_cluster:
        port = os.environ.get("STREAMLIT_SERVER_PORT", "8501")
        status = http_status(f"http://127.0.0.1:{port}/_stcore/health")
        check(f"Pod Streamlit /_stcore/health :{port}", status == 200, str(status))
        bundle = os.environ.get("SSL_CERT_FILE", "")
        certs = Path(bundle).read_text(errors="ignore").count("BEGIN CERTIFICATE") if bundle and Path(bundle).is_file() else 0
        check("CA bundle (SSL_CERT_FILE)", certs > 1, f"{certs} certificates")
        check("REQUESTS_CA_BUNDLE", os.environ.get("REQUESTS_CA_BUNDLE") == bundle and bool(bundle))
    else:
        try:
            with socket.create_connection(("127.0.0.1", 8501), timeout=2):
                check("Streamlit :8501", True)
        except OSError:
            check("Streamlit :8501", False, "run scripts/start-demo.sh")
    if args.live:
        # TLS-verified reachability of the addresses the SDKs use (no credentials sent).
        check("AO API /healthcheck", http_status(f"{backend['api_url']}/healthcheck") == 200)
        ingest_base = backend["ingest_url"] or backend["api_url"]
        check("AO ingest /ingest/healthz", http_status(f"{ingest_base}/ingest/healthz") == 200, ingest_base.split("://")[-1].split("/")[0])
        check("Agent Control /health", http_status(f"{backend['agent_control_url']}/health") == 200)
        try:
            import importlib
            from helpers.galileo_ingest import configure_ingest_url
            from galileo import GalileoLogger
            configure_ingest_url(backend["ingest_url"])
            native = GalileoLogger._is_ingest_service_available()
            if not native:
                # The SDK probe has a fixed 2 s timeout and caches the result; retry once.
                importlib.import_module("galileo.logger.logger")._ingest_service_cache.clear()
                native = GalileoLogger._is_ingest_service_available()
            check("SDK uses the native ingest door", native)
        except Exception as exc:
            check("SDK uses the native ingest door", False, type(exc).__name__)
    if args.live and "galileo_api_key" not in failures:
        try:
            from helpers.galileo_api_helpers import get_galileo_project_id, get_galileo_log_stream_id
            cfg = domain.config["galileo"]
            project_id = get_galileo_project_id(cfg["project"])
            stream_id = get_galileo_log_stream_id(project_id, cfg["log_stream"]) if project_id else None
            check("Project / log stream", bool(stream_id))
        except Exception as exc:
            check("Project / log stream", False, type(exc).__name__)
        if args.in_cluster:
            check_agent_control_registration(check)
    if args.live and "openai_api_key" not in failures:
        from helpers.llm_utils import get_chat_model, get_model_runtime_options, message_content_to_text
        model_cfg = domain.config["model"]
        models = [model_cfg["hosted_default_model"]]
        # Domains with explicit hosted API settings (e.g. a model A/B) check every hosted model.
        if get_model_runtime_options(model_cfg, models[0], "hosted"):
            models += [m for m in model_cfg.get("hosted_additional_models") or [] if m not in models]
        for model in models:
            try:
                options = get_model_runtime_options(model_cfg, model, "hosted")
                llm = get_chat_model(model, provider="hosted", temperature=0, **options)
                result = llm.invoke("Reply with OK.")
                check(f"LLM endpoint ({model})", bool(message_content_to_text(result.content).strip()))
            except Exception as exc:
                check(f"LLM endpoint ({model})", False, type(exc).__name__)
    print("Manual checks still required: evaluator results, policies, traces and experiments.")
    return int(bool(failures))


def http_status(url, timeout=5):
    """HTTP status of a GET (TLS verified with the active CA bundle); None when unreachable."""
    context = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


def check_agent_control_registration(check):
    """Read back the registered Agent Control agent (the app registers it on first use)."""
    import asyncio
    try:
        import agent_control

        async def read():
            async with agent_control.AgentControlClient(
                base_url=os.environ["AGENT_CONTROL_URL"], api_key=os.environ["GALILEO_API_KEY"],
                api_key_header=os.environ.get("AGENT_CONTROL_API_KEY_HEADER", "Galileo-API-Key"), timeout=10,
            ) as client:
                return await agent_control.agents.get_agent(client, os.environ["AGENT_CONTROL_AGENT_NAME"])

        asyncio.run(read())
        check("Agent Control agent registered", True, os.environ.get("AGENT_CONTROL_AGENT_NAME", ""))
    except Exception as exc:
        check("Agent Control agent registered", False, f"{type(exc).__name__}; open the app once to register it")


if __name__ == "__main__":
    raise SystemExit(main())
