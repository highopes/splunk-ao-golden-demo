#!/usr/bin/env python3
"""Create or update the three Healthcare demo Controls and bind them to the domain's Log Stream.

  python scripts/setup_demo_controls.py                         # SQL enabled; PII / Injection disabled
  python scripts/setup_demo_controls.py --enable sql,pii,injection
  python scripts/setup_demo_controls.py --disable injection     # change binding state only

Works for every backend profile (splunkse and imlab-onprem); the Luna (SLM)
scorer IDs are looked up by label on the active backend. Idempotent: existing
Controls with the same name get their definition replaced, bindings are upserted.
Names: splunk-ao-golden-demo-block-harmful-sql / -block-output-pii / -block-prompt-injection.
Never prints credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PREFIX = "splunk-ao-golden-demo-"
DESCRIPTION = "Synthetic Healthcare Golden Demo; bound only to this demo stream"
SHORT = {"sql": "block-harmful-sql", "pii": "block-output-pii", "injection": "block-prompt-injection"}


def sql_control() -> dict:
    return {
        "description": DESCRIPTION, "enabled": True, "execution": "server",
        "scope": {"step_types": ["tool"], "step_names": ["delete_patient_record"], "stages": ["pre"]},
        "condition": {"selector": {"path": "input.sql"}, "evaluator": {"name": "sql", "config": {
            "dialect": "postgres", "blocked_operations": ["DELETE"], "block_ddl": True, "block_dcl": True,
            "allow_multi_statements": True, "case_sensitive": False,
            "column_context_scope": "all", "column_presence_logic": "any"}}},
        "action": {"decision": "deny"},
    }


def luna_leaf(scorer: dict, operator: str, threshold: str) -> dict:
    return {"selector": {"path": "*"}, "evaluator": {"name": "galileo.luna", "config": {
        "scorer_id": scorer["id"], "scorer_version_id": scorer["version_id"], "scorer_label": scorer["label"],
        "operator": operator, "threshold": threshold, "payload_field": "input", "timeout_ms": 10000}}}


def pii_control(scorer: dict) -> dict:
    # Luna "any" ignores the category list (a name alone would trigger); one "contains" per category.
    return {
        "description": DESCRIPTION, "enabled": True, "execution": "server",
        "scope": {"step_types": ["llm"], "step_names": ["Healthcare Assistant"], "stages": ["post"]},
        "condition": {"or": [luna_leaf(scorer, "contains", "phone_number"), luna_leaf(scorer, "contains", "address")]},
        "action": {"decision": "steer", "steering_context": {"message": "Remove phone number and address from output"}},
    }


def injection_control(scorer: dict, threshold: str) -> dict:
    return {
        "description": DESCRIPTION, "enabled": True, "execution": "server",
        "scope": {"step_types": ["llm"], "step_names": ["Healthcare Assistant"], "stages": ["pre"]},
        "condition": luna_leaf(scorer, "gte", threshold),
        "action": {"decision": "deny"},
    }


def find_scorer(label: str) -> dict:
    from galileo.scorers import Scorers

    for scorer in Scorers().list():
        if getattr(scorer, "label", None) == label:
            return {"id": str(scorer.id), "version_id": str(scorer.default_version_id), "label": label}
    raise SystemExit(f"Scorer {label!r} is not available on this backend")


async def apply(definitions: dict, enabled: set, target_id: str) -> None:
    import agent_control
    from agent_control.control_bindings import upsert_control_binding_by_key
    from agent_control.controls import create_control, list_controls, set_control_data
    from agent_control_models import ControlDefinition

    async with agent_control.AgentControlClient(
        base_url=os.environ["AGENT_CONTROL_URL"], api_key=os.environ["GALILEO_API_KEY"],
        api_key_header=os.environ.get("AGENT_CONTROL_API_KEY_HEADER", "Galileo-API-Key"), timeout=30,
    ) as client:
        for key, data in definitions.items():
            name = PREFIX + SHORT[key]
            existing = [c for c in (await list_controls(client, name=name, limit=100))["controls"] if c["name"] == name]
            if data is None:
                if not existing:
                    raise SystemExit(f"{name} does not exist; run without --bindings-only first")
                control_id = existing[0]["id"]
            elif existing:
                control_id = existing[0]["id"]
                await set_control_data(client, control_id, ControlDefinition.model_validate(data))
            else:
                control_id = (await create_control(client, name=name, data=ControlDefinition.model_validate(data)))["control_id"]
            await upsert_control_binding_by_key(
                client, target_type="log_stream", target_id=target_id, control_id=control_id, enabled=key in enabled)
            print(f"{name}: id={control_id} binding={'enabled' if key in enabled else 'disabled'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain", default="healthcare")
    parser.add_argument("--enable", default="sql", help="Comma list of bindings to enable: sql,pii,injection (others disabled)")
    parser.add_argument("--disable", default="", help="Comma list to disable (applied after --enable)")
    parser.add_argument("--bindings-only", action="store_true", help="Only change binding state; keep definitions")
    parser.add_argument("--injection-threshold", default="0.80")
    args = parser.parse_args()
    enabled = {x for x in args.enable.split(",") if x} - {x for x in args.disable.split(",") if x}
    unknown = enabled - set(SHORT)
    if unknown:
        parser.error(f"unknown control(s): {', '.join(sorted(unknown))}")

    from domain_manager import DomainManager
    from setup_env import setup_environment

    config = DomainManager().load_domain_config(args.domain).config
    setup_environment(args.domain, config)
    from helpers.galileo_api_helpers import get_galileo_log_stream_id, get_galileo_project_id
    from helpers.galileo_compat import tolerate_unknown_permission_actions

    tolerate_unknown_permission_actions()
    project_id = get_galileo_project_id(config["galileo"]["project"])
    stream_id = get_galileo_log_stream_id(project_id, config["galileo"]["log_stream"]) if project_id else None
    if not stream_id:
        raise SystemExit("Project / Log Stream not found; send one chat message in the app first")
    if args.bindings_only:
        definitions = {key: None for key in SHORT}
    else:
        definitions = {
            "sql": sql_control(),
            "pii": pii_control(find_scorer("Output PII (SLM)")),
            "injection": injection_control(find_scorer("Prompt Injection (SLM)"), args.injection_threshold),
        }
    asyncio.run(apply(definitions, enabled, stream_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
