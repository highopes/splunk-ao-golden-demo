#!/usr/bin/env python3
"""Read-only preflight. Never prints credentials; cloud checks are opt-in."""
import argparse
import importlib.metadata
import os
from pathlib import Path
import socket
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="healthcare")
    parser.add_argument("--live", action="store_true", help="Read cloud project/stream and request a small LLM completion")
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
    check("backend_profile", secrets.get("backend_profile", "splunkse") == "splunkse")
    from setup_env import _derive_galileo_api_url, _derive_agent_control_url
    console_url = secrets.get("galileo_console_url", "https://console.multitenant.galileocloud.io").rstrip("/")
    api_url = _derive_galileo_api_url(console_url, secrets.get("galileo_api_url", ""))
    control_url = _derive_agent_control_url(console_url, secrets.get("agent_control_url", ""))
    check("SDK Console base URL", console_url == "https://console.multitenant.galileocloud.io")
    check("SDK API base URL (explicit or derived)", api_url == "https://api.multitenant.galileocloud.io")
    check("Control URL (explicit or derived)", control_url == "https://console.multitenant.galileocloud.io/api/agent-control")
    check("splunkse Console entry", secrets.get("demo_console_url", "https://console.multitenant.galileocloud.io/splunkse").rstrip("/") == "https://console.multitenant.galileocloud.io/splunkse")
    check("Control authentication header name", secrets.get("agent_control_api_key_header", "Galileo-API-Key") == "Galileo-API-Key")
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
    except Exception as exc:
        check("Database / domain data", False, type(exc).__name__ + "; start DB and load domain data")
    try:
        with socket.create_connection(("127.0.0.1", 8501), timeout=2):
            check("Streamlit :8501", True)
    except OSError:
        check("Streamlit :8501", False, "run scripts/start-demo.sh")
    if args.live and "galileo_api_key" not in failures:
        try:
            from helpers.galileo_api_helpers import get_galileo_project_id, get_galileo_log_stream_id
            cfg = domain.config["galileo"]
            project_id = get_galileo_project_id(cfg["project"])
            stream_id = get_galileo_log_stream_id(project_id, cfg["log_stream"]) if project_id else None
            check("Cloud project / log stream", bool(stream_id))
        except Exception as exc:
            check("Cloud project / log stream", False, type(exc).__name__)
    if args.live and "openai_api_key" not in failures:
        try:
            from helpers.llm_utils import get_chat_model
            llm = get_chat_model(domain.config["model"]["hosted_default_model"], provider="hosted", temperature=0)
            result = llm.invoke("Reply with OK.")
            check("LLM endpoint", bool(result.content))
        except Exception as exc:
            check("LLM endpoint", False, type(exc).__name__)
    print("Manual checks still required: evaluator results, policies, traces and experiments.")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
