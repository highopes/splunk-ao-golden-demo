#!/usr/bin/env python3
"""Cisco SE Model Economics A/B: one Experiment per model on the same Dataset.

Preflight (stops at the first failure; --preflight-only creates nothing):
  secrets present (never printed); local Dataset matches
  domains/cisco_se/dataset_sources.yaml; strict pgvector index metadata;
  retrieval returns both Cisco and H3C facts; tenant Scorers (Ground Truth
  Adherence, Context Adherence) available; each model completes a real
  tool call -> tool result -> answer and returns the expected model ID;
  Project / Group / cloud Dataset state; reliable ingest (platform cost
  computation) enabled.

Run: runs each Experiment through experiments/experiment_helpers.py (the same
Agent, RAG and lineage tags as the Streamlit Experiments page), all in the
cisco_se Experiment Group. Reads back Group membership, tags, root Trace
count, Judge status and platform cost, then writes a JSON run manifest
(no secrets).

Usage: ./scripts/run-cisco-se-ab [--preflight-only] [--models gpt-5-nano,gpt-6.1-sol]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import yaml  # noqa: E402

from domain_manager import DomainManager  # noqa: E402
from experiments.cisco_se_economics import (  # noqa: E402
    AGENT_ERROR_PREFIXES,
    GROUND_TRUTH_ALIASES,
    api_call,
    fetch_records,
    find_metric,
    metric_status,
    model_matches,
    to_plain,
)
from helpers.galileo_compat import tolerate_unknown_permission_actions  # noqa: E402
from helpers.galileo_ingest import reliable_ingest_requested  # noqa: E402
from setup_env import get_domain_project_name, setup_environment  # noqa: E402

DOMAIN = "cisco_se"
DATASET_FILE = ROOT / "domains" / DOMAIN / "dataset.csv"
SOURCES_FILE = ROOT / "domains" / DOMAIN / "dataset_sources.yaml"
TOOL_SCHEMA_FILE = ROOT / "domains" / DOMAIN / "tools" / "schema.json"
SCORER_LABELS = ("Ground Truth Adherence", "Context Adherence")
REQUIRED_TAGS = (
    "application_model", "model_provider", "api_mode", "reasoning_effort",
    "dataset_hash", "dataset_version", "code_version", "chaos_state", "run_id",
)
SMOKE_QUERIES = (
    ("Cisco", "N9332D-H2R 400G ports rack units"),
    ("H3C", "S9827-64EP interface type"),
)
MODEL_SMOKE_PROMPT = (
    "Use the search_cisco_se_specs tool to look up the Cisco N9332D-H2R 400G port count, "
    "then answer in one short sentence."
)


class PreflightError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def report(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'✅ PASS' if ok else '❌ FAIL'}  {label}{(': ' + detail) if detail else ''}", flush=True)


def require(ok: bool, label: str, detail: str = "") -> None:
    report(ok, label, detail)
    if not ok:
        raise PreflightError(f"{label}: {detail}" if detail else label)


def parse_args(config: Dict[str, Any]) -> argparse.Namespace:
    model_cfg = config.get("model") or {}
    domain_models = [model_cfg.get("hosted_default_model"), *(model_cfg.get("hosted_additional_models") or [])]
    domain_models = [m for m in domain_models if m]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default=",".join(domain_models),
                        help=f"Comma-separated Model A,B (default: {','.join(domain_models)})")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                        help="Run identifier shared by both Experiments (default: UTC timestamp)")
    parser.add_argument("--preflight-only", action="store_true", help="Run all preflight checks only; create and run nothing")
    parser.add_argument("--manifest-dir", default=str(ROOT / "data" / "cisco_se_ab_runs"),
                        help="JSON run manifest directory (default: data/cisco_se_ab_runs)")
    parser.add_argument("--readback-timeout", type=int, default=900,
                        help="Seconds to wait for root Traces and Judge scores after each run (default: 900)")
    args = parser.parse_args()
    args.models = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [m for m in args.models if m not in domain_models]
    if unknown:
        parser.error(f"Models not offered by the cisco_se domain: {', '.join(unknown)}")
    if len(args.models) != len(set(args.models)) or not args.models:
        parser.error("--models must list distinct models")
    return args


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #

def check_local_dataset(config: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    from experiments.experiment_helpers import dataset_content_hash, local_dataset_records, scenario_key

    records = local_dataset_records(str(DATASET_FILE))
    local_hash = dataset_content_hash(records)
    require(local_hash == plan.get("dataset_hash"), "Local Dataset content hash",
            f"{local_hash[:12]}… / dataset_sources.yaml {str(plan.get('dataset_hash'))[:12]}…")
    version = (config.get("experiments") or {}).get("dataset_version")
    require(version == plan.get("dataset_version"), "Dataset version", str(version))
    local_keys = {scenario_key(i) for i, _ in records}
    planned = {str(q["scenario_key"]) for q in plan.get("questions") or []}
    require(local_keys == planned and len(records) == len(planned), "Question scenario_key", f"{len(records)} questions")
    return {"hash": local_hash, "version": version, "rows": len(records)}


def check_index_and_retrieval(config: Dict[str, Any]) -> Dict[str, Any]:
    from agent_frameworks.langgraph.langgraph_rag import get_domain_rag_system
    from helpers.pgvector_utils import verify_strict_index

    try:
        info = verify_strict_index(DOMAIN, config.get("vectorstore") or {})
    except Exception as exc:
        require(False, "Strict index", str(exc))
    report(True, "Strict index", f"{info['collection_name']} {info['embedding_model']} dim={info.get('embedding_dimensions')}")
    rag = get_domain_rag_system(DOMAIN)
    for vendor, query in SMOKE_QUERIES:
        result = asyncio.run(rag.search_documents(query))
        vendors = {d.get("vendor") for d in result.get("documents") or []}
        require(vendor in vendors, f"Retrieval smoke test ({vendor})", f"{query!r} -> {sorted(v for v in vendors if v)}")
    return info


def check_scorers() -> List[Dict[str, Any]]:
    from galileo.scorers import Scorers

    found = api_call("List Scorers", lambda: Scorers().list_by_labels(list(SCORER_LABELS), strict=False))
    result = []
    for label in SCORER_LABELS:
        match = next((s for s in found if s.label == label), None) or next((s for s in found if s.name == label), None)
        require(match is not None, f"Scorer {label!r}", "available" if match else "not available in this tenant")
        result.append({"label": label, "name": match.name, "id": str(match.id)})
        print(f"      {label}: name={match.name} id={match.id}")
    return result


def check_model(model: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Real tool call -> real retrieval result -> final answer, without Galileo logging."""
    from langchain_core.messages import HumanMessage, ToolMessage

    from agent_frameworks.langgraph.langgraph_rag import get_domain_rag_system
    from helpers.llm_utils import describe_model_runtime, get_chat_model, get_model_runtime_options, message_content_to_text

    options = get_model_runtime_options(config.get("model") or {}, model, "hosted")
    runtime = describe_model_runtime(model, "hosted", options)
    tools = [{"type": "function", "function": s} for s in json.loads(TOOL_SCHEMA_FILE.read_text(encoding="utf-8"))]
    tool_name = tools[0]["function"]["name"]
    llm = get_chat_model(model, provider="hosted", **options)
    messages: List[Any] = [HumanMessage(MODEL_SMOKE_PROMPT)]
    try:
        first = llm.bind_tools(tools, tool_choice=tool_name).invoke(messages)
    except Exception as exc:
        require(False, f"Model {model}: tool call", f"{type(exc).__name__}: {exc}")
    calls = [c for c in first.tool_calls if c.get("name") == tool_name]
    require(bool(calls), f"Model {model}: tool call", f"{len(first.tool_calls)} tool call(s)")
    query = str(calls[0]["args"].get("query") or "")
    result = asyncio.run(get_domain_rag_system(DOMAIN).search_documents(query))
    messages += [first, ToolMessage(json.dumps(result, ensure_ascii=False), tool_call_id=calls[0]["id"])]
    try:
        final = llm.bind_tools(tools).invoke(messages)
    except Exception as exc:
        require(False, f"Model {model}: answer from tool result", f"{type(exc).__name__}: {exc}")
    answer = message_content_to_text(final.content).strip()
    require(bool(answer), f"Model {model}: answer from tool result", f"{len(answer)} characters")
    returned = str(final.response_metadata.get("model_name") or final.response_metadata.get("model") or "")
    require(model_matches(returned, model), f"Model {model}: returned model ID", returned or "missing")
    usage = dict(final.usage_metadata or {})
    print(f"      runtime={runtime} usage={usage}")
    return {"model": model, "returned_model": returned, "runtime": runtime, "smoke_usage": usage}


def check_platform(project: str, group: str, dataset_name: str, local_hash: str, create: bool,
                   config: Dict[str, Any]) -> Dict[str, Any]:
    from galileo.datasets import get_dataset
    from galileo.experiments import list_experiment_groups
    from galileo.projects import create_project, get_project

    from experiments.experiment_helpers import create_domain_dataset, dataset_content_hash, remote_dataset_records

    state: Dict[str, Any] = {"project": project, "group": group, "dataset_name": dataset_name}
    project_obj = api_call("Get Project", lambda: get_project(name=project))
    if project_obj is None:
        if not create:
            report(True, "Project", f"{project!r} does not exist yet (created on the real run)")
            report(True, "Reliable ingest (platform cost)", "enabled for this Project on the real run")
            return state
        project_obj = api_call("Create Project", lambda: create_project(project))
        report(True, "Project", f"created {project!r}")
    else:
        report(True, "Project", f"{project!r} exists")
    state["project_id"] = str(project_obj.id)
    if create:
        from helpers.galileo_ingest import apply_domain_reliable_ingest

        enabled = apply_domain_reliable_ingest(config, state["project_id"])
        require(enabled, "Reliable ingest (platform cost)", "reliable=True enabled for this Project" if enabled else
                "cisco_se config lacks galileo.reliable_ingest: true; the platform would record app cost as 0")
    else:
        report(bool(reliable_ingest_requested(config)), "Reliable ingest (platform cost)",
               "galileo.reliable_ingest: true (enabled on the real run)" if reliable_ingest_requested(config)
               else "cisco_se config lacks galileo.reliable_ingest: true")
    groups = api_call("List Experiment Groups", lambda: list_experiment_groups(project_id=state["project_id"]))
    match = next((g for g in groups or [] if getattr(g, "name", None) == group), None)
    state["group_id"] = str(match.id) if match else None
    report(True, "Experiment Group", f"{group!r} {'exists' if match else 'will be created by the first Experiment'}")

    dataset = api_call("Get cloud Dataset", lambda: get_dataset(name=dataset_name, project_name=project))
    if dataset is None:
        if not create:
            report(True, "Cloud Dataset", f"{dataset_name!r} does not exist yet (created on the real run)")
            return state
        dataset = create_domain_dataset(DOMAIN, str(DATASET_FILE), custom_name=dataset_name)
        report(True, "Cloud Dataset", f"created {dataset_name!r}")
    remote_hash = dataset_content_hash(remote_dataset_records(dataset))
    hash_detail = f"cloud {remote_hash[:12]}… / local {local_hash[:12]}…"
    if remote_hash != local_hash:
        hash_detail += "; for a new version change experiments.dataset_name"
    require(remote_hash == local_hash, "Cloud Dataset content hash", hash_detail)
    state.update({
        "dataset": dataset,
        "dataset_id": str(dataset.dataset.id),
        "dataset_version_index": dataset.dataset.current_version_index,
    })
    return state


# --------------------------------------------------------------------------- #
# Run and readback
# --------------------------------------------------------------------------- #

def readback(project_id: str, group: str, experiment_id: str, model: str, expected_rows: int,
             dataset_hash: str, timeout: int) -> Dict[str, Any]:
    from galileo.experiment_tags import get_experiment_tags
    from galileo.experiments import get_experiments
    from galileo.search import get_traces

    deadline = time.monotonic() + timeout
    traces: List[Dict[str, Any]] = []
    scored = 0
    while True:
        traces = fetch_records(
            lambda **page: get_traces(project_id=project_id, experiment_id=experiment_id, **page),
            "Read Experiment Traces",
        )
        statuses = [metric_status(find_metric(t, GROUND_TRUTH_ALIASES)[1]) for t in traces]
        scored = sum(1 for s in statuses if s in ("success", "failed", "error", "not_computed"))
        if len(traces) >= expected_rows and scored >= len(traces):
            break
        if time.monotonic() >= deadline:
            break
        print(f"      ⏳ Waiting for the platform: root Traces {len(traces)}/{expected_rows}, Ground Truth Adherence final {scored}", flush=True)
        time.sleep(20)
    tags = {str(t.key): str(t.value) for t in api_call("Read Experiment tags", lambda: get_experiment_tags(project_id, experiment_id)) or []}
    members = api_call("Check Group membership", lambda: get_experiments(project_id=project_id, experiment_group=group)) or []
    member = next((to_plain(e) for e in members if getattr(e, "id", None) == experiment_id), None)
    warnings = []
    if member is None:
        warnings.append(f"Experiment {experiment_id} is not in Group {group!r}")
    missing_tags = [t for t in REQUIRED_TAGS if not tags.get(t)]
    if missing_tags:
        warnings.append(f"Missing tags: {', '.join(missing_tags)}")
    if tags.get("application_model") != model:
        warnings.append(f"application_model tag {tags.get('application_model')!r} differs from {model!r}")
    if tags.get("dataset_hash") != dataset_hash:
        warnings.append("dataset_hash tag differs from the local dataset plan")
    if len(traces) != expected_rows:
        warnings.append(f"{len(traces)} root Traces, expected {expected_rows}")
    if scored < len(traces):
        warnings.append(f"Ground Truth Adherence is still pending for {len(traces) - scored} Trace(s); rerun the exporter later")
    errors = sum(1 for t in traces if str(t.get("output") or "").strip().startswith(AGENT_ERROR_PREFIXES))
    if errors:
        warnings.append(f"{errors} Trace(s) returned an Agent error")
    costs = [m.get("cost") for m in ((t.get("metrics") or {}) for t in traces)]
    priced = [c for c in costs if isinstance(c, (int, float)) and c > 0]
    zero_cost = sum(1 for c in costs if c == 0)
    if zero_cost:
        warnings.append(f"{zero_cost} Trace(s) have platform app cost 0 (check galileo.reliable_ingest and model prices)")
    app_cost = sum(priced) if priced else None
    for w in warnings:
        print(f"⚠️  {w}")
    cost_text = f"{app_cost:.6f}" if app_cost is not None else "n/a"
    report(not warnings, "Platform read-back",
           f"{len(traces)} root Traces, GT final {scored}, {len(tags)} tags, "
           f"in Group={'yes' if member else 'no'}, total app cost USD={cost_text}")
    return {
        "root_traces": len(traces),
        "ground_truth_final": scored,
        "agent_error_traces": errors,
        "priced_traces": len(priced),
        "app_cost_usd": app_cost,
        "tags": tags,
        "group_member": member is not None,
        "experiment_group_id": (member or {}).get("experiment_group_id"),
        "dataset": (member or {}).get("dataset"),
        "warnings": warnings,
    }


def write_manifest(manifest_dir: str, run_id: str, manifest: Dict[str, Any]) -> str:
    os.makedirs(manifest_dir, exist_ok=True)
    path = os.path.join(manifest_dir, f"{run_id}.json")
    fd, tmp = tempfile.mkstemp(prefix=".manifest_", suffix=".json.tmp", dir=manifest_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")
    os.replace(tmp, path)
    return path


def main() -> int:
    config = DomainManager().load_domain_config(DOMAIN).config
    args = parse_args(config)
    plan = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8")) or {}
    project = get_domain_project_name(DOMAIN, config)
    experiments_cfg = config.get("experiments") or {}
    group = experiments_cfg.get("group")
    dataset_name = experiments_cfg.get("dataset_name")
    if not group or not dataset_name:
        raise PreflightError("cisco_se config needs experiments.group and experiments.dataset_name")

    setup_environment(DOMAIN, config)
    tolerate_unknown_permission_actions()
    from helpers.llm_utils import openai_api_key_configured, set_llm_provider
    from experiments.experiment_helpers import chaos_state, code_version

    set_llm_provider("hosted")
    print(f"\n🚀 Cisco SE Model Economics A/B  run_id={args.run_id}  models={', '.join(args.models)}")
    print(f"   Project={project}  Group={group}")
    print("\n🔍 Preflight (stops at the first failure; never falls back to another model or cached answers)")
    require(openai_api_key_configured(), "OpenAI API Key", "configured" if openai_api_key_configured() else "missing from .streamlit/secrets.toml")
    require(bool(os.environ.get("GALILEO_API_KEY")), "Splunk AO API Key", "configured" if os.environ.get("GALILEO_API_KEY") else "missing")
    chaos = chaos_state()
    require(chaos == "off", "Chaos state", chaos)
    local = check_local_dataset(config, plan)
    index = check_index_and_retrieval(config)
    scorers = check_scorers()
    models = [check_model(m, config) for m in args.models]
    platform = check_platform(project, group, dataset_name, local["hash"], create=not args.preflight_only, config=config)

    manifest: Dict[str, Any] = {
        "schema_version": 1,
        "run_id": args.run_id,
        "started_at_utc": utc_now(),
        "code_version": code_version(),
        "chaos_state": chaos,
        "project": project,
        "project_id": platform.get("project_id"),
        "experiment_group": group,
        "dataset": {
            "name": dataset_name,
            "id": platform.get("dataset_id"),
            "version_index": platform.get("dataset_version_index"),
            "dataset_version": local["version"],
            "dataset_hash": local["hash"],
            "rows": local["rows"],
        },
        "index": index,
        "scorers": scorers,
        "models": models,
        "experiments": [],
        "status": "preflight_passed",
    }
    if args.preflight_only:
        print("\n✅ All preflight checks passed (nothing created or run).")
        return 0

    from galileo.schema.metrics import GalileoMetrics
    from agent_factory import AgentFactory
    from experiments.experiment_helpers import run_domain_experiment

    factory = AgentFactory()
    manifest["status"] = "running"
    try:
        for model in args.models:
            name = f"{group} - {model} - {args.run_id}"
            print(f"\n🧪 Running Experiment: {name}", flush=True)
            started = utc_now()
            t0 = time.monotonic()
            results = run_domain_experiment(
                DOMAIN, name, platform["dataset"], factory,
                metrics=[GalileoMetrics.ground_truth_adherence, GalileoMetrics.context_adherence],
                project=project, model_name=model, llm_provider="hosted",
                experiment_group=group, experiment_tags={"run_id": args.run_id},
            )
            experiment = results.get("experiment") if isinstance(results, dict) else None
            if experiment is None:
                raise RuntimeError(f"run_experiment returned no Experiment for {model}")
            entry = {
                "model": model,
                "experiment_id": str(experiment.id),
                "experiment_name": getattr(experiment, "name", name),
                "link": results.get("link"),
                "started_at_utc": started,
                "run_wall_clock_seconds": round(time.monotonic() - t0, 3),
            }
            print(f"   Experiment {entry['experiment_name']} ({entry['experiment_id']})\n   {entry['link']}")
            print(f"   Run took {entry['run_wall_clock_seconds']:.1f} s; reading back platform data (waiting up to {args.readback_timeout} s)")
            entry.update(readback(platform["project_id"], group, entry["experiment_id"], model,
                                  local["rows"], local["hash"], args.readback_timeout))
            manifest["experiments"].append(entry)
            write_manifest(args.manifest_dir, args.run_id, manifest)
        manifest["status"] = "completed_with_warnings" if any(e["warnings"] for e in manifest["experiments"]) else "completed"
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        manifest["finished_at_utc"] = utc_now()
        path = write_manifest(args.manifest_dir, args.run_id, manifest)
        print(f"\n📄 Run manifest: {path}  status={manifest['status']}")
    print("\n➡️  Next: ./scripts/export-cisco-se-economics")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PreflightError as exc:
        print(f"\n❌ Preflight failed: {exc}", file=sys.stderr)
        sys.exit(2)
