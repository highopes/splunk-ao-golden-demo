#!/usr/bin/env python3
"""Cisco SE Model Economics: read-only export of Experiment results to a flat CSV.

Reads .streamlit/secrets.toml through setup_env, queries the Experiments,
tags, root Traces and child Spans of the Experiment Group in the cisco_se
Project, writes one row per root Trace and prints a per-Experiment summary.
It runs no LLM, Experiment or Control and writes nothing to the platform.

Data contract: documentation/CISCO_SE_MODEL_ECONOMICS_CSV.md
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import yaml  # noqa: E402

from domain_manager import DomainManager  # noqa: E402
from experiments.cisco_se_economics import (  # noqa: E402
    DEFAULT_GT_PASS_THRESHOLD,
    DatasetPlan,
    ExperimentData,
    ExportError,
    api_call,
    build_rows,
    fetch_records,
    format_summary,
    pairing_warnings,
    summarize,
    to_plain,
    write_csv_atomic,
)
from helpers.galileo_compat import tolerate_unknown_permission_actions  # noqa: E402
from setup_env import get_domain_project_name, setup_environment  # noqa: E402

DOMAIN = "cisco_se"
DEFAULT_OUTPUT = ROOT / "data" / "cisco_se_model_economics.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="CSV output path (default: data/cisco_se_model_economics.csv)")
    parser.add_argument("--project", help="Project name (default: cisco_se galileo.project); Projects of other domains are rejected")
    parser.add_argument("--group", help="Experiment Group name (default: cisco_se experiments.group)")
    parser.add_argument("--prefix", help="Only export Experiments whose name starts with this prefix")
    parser.add_argument("--experiment-ids", help="Comma-separated Experiment IDs (must belong to the Group)")
    parser.add_argument("--gt-pass-threshold", type=float, default=DEFAULT_GT_PASS_THRESHOLD,
                        help=f"Ground Truth Adherence pass threshold on the 0..1 score (default: {DEFAULT_GT_PASS_THRESHOLD})")
    args = parser.parse_args()
    if not 0.0 <= args.gt_pass_threshold <= 1.0:
        parser.error("--gt-pass-threshold must be between 0 and 1")
    return args


def resolve_scope(args: argparse.Namespace):
    manager = DomainManager()
    config = manager.load_domain_config(DOMAIN).config
    own_project = get_domain_project_name(DOMAIN, config)
    project = (args.project or own_project).strip()
    other_projects = {
        get_domain_project_name(d, manager.load_domain_config(d).config)
        for d in manager.list_domains() if d != DOMAIN
    }
    if project in other_projects:
        raise ExportError(f"Project {project!r} belongs to another domain; this exporter only reads the Cisco SE scenario")
    group = (args.group or (config.get("experiments") or {}).get("group") or "").strip()
    if not group:
        raise ExportError("No Experiment Group configured (cisco_se experiments.group) and no --group given")
    with open(ROOT / "domains" / DOMAIN / "dataset_sources.yaml", encoding="utf-8") as handle:
        plan = DatasetPlan.from_yaml(yaml.safe_load(handle) or {})
    if not plan.dataset_hash or not plan.scenario_ids:
        raise ExportError("domains/cisco_se/dataset_sources.yaml is missing dataset_hash or the question list")
    return config, project, group, plan


def select_experiments(experiments, group: str, prefix: str | None, ids: list[str]):
    selected = []
    for exp in experiments:
        values = to_plain(exp) or {}
        if values.get("experiment_group_name") and values["experiment_group_name"] != group:
            continue
        if prefix and not str(values.get("name") or "").startswith(prefix):
            continue
        if ids and values.get("id") not in ids:
            continue
        selected.append(values)
    if ids:
        missing = sorted(set(ids) - {v.get("id") for v in selected})
        if missing:
            raise ExportError(f"Experiment IDs not found in Group {group!r}: {', '.join(missing)}")
    return sorted(selected, key=lambda v: (str(v.get("created_at") or ""), str(v.get("id") or "")))


def main() -> int:
    args = parse_args()
    _, project, group, plan = resolve_scope(args)
    setup_environment()
    tolerate_unknown_permission_actions()
    if not os.environ.get("GALILEO_API_KEY"):
        raise ExportError(".streamlit/secrets.toml has no galileo_api_key")

    from galileo.experiment_tags import get_experiment_tags
    from galileo.experiments import get_experiments
    from galileo.projects import get_project
    from galileo.search import get_spans, get_traces

    print(f"🔎 [1/4] Looking up Project: {project}")
    project_obj = api_call("Get Project", lambda: get_project(name=project))
    if project_obj is None:
        raise ExportError(f"Project {project!r} not found")
    project_id = str(project_obj.id)
    print(f"🔎 [2/4] Querying Experiment Group: {group}")
    experiments = api_call(
        "Query Experiment Group",
        lambda: get_experiments(project_id=project_id, experiment_group=group),
    )
    if not isinstance(experiments, list):
        raise ExportError(f"Experiment Group query returned unexpected type {type(experiments).__name__}")
    ids = [i.strip() for i in (args.experiment_ids or "").split(",") if i.strip()]
    selected = select_experiments(experiments, group, args.prefix, ids)
    if not selected:
        raise ExportError(f"No Experiment in Group {group!r} of Project {project!r} matches the filters")
    print(f"📥 [3/4] Reading tags, root Traces and Spans of {len(selected)} Experiment(s) (read-only)")

    data: list[ExperimentData] = []
    for exp in selected:
        experiment_id = str(exp["id"])
        label = f"Experiment {exp.get('name')!r}"
        print(f"   · Reading {label} …")
        tags = {
            str(t.key): str(t.value)
            for t in api_call(f"Read {label} tags", lambda: get_experiment_tags(project_id, experiment_id)) or []
        }
        traces = fetch_records(
            lambda **page: get_traces(project_id=project_id, experiment_id=experiment_id, **page),
            f"Read {label} Traces",
        )
        spans = fetch_records(
            lambda **page: get_spans(project_id=project_id, experiment_id=experiment_id, **page),
            f"Read {label} Spans",
        )
        print(f"     {len(traces)} root Traces, {len(spans)} Spans, {len(tags)} tags")
        data.append(ExperimentData(experiment=exp, tags=tags, traces=traces, spans=spans))

    exported_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    result = build_rows(
        project_name=project,
        project_id=project_id,
        experiments=data,
        plan=plan,
        exported_at=exported_at,
        gt_pass_threshold=args.gt_pass_threshold,
    )
    if not result.rows:
        raise ExportError("The selected Experiments returned no root Traces; the existing CSV was left unchanged")
    output = os.path.abspath(args.output)
    print("💾 [4/4] Writing CSV atomically and validating the read-back")
    rows = write_csv_atomic(result.rows, output)
    print(f"\n✅ Wrote {len(rows)} rows: {output}")
    print(f"Project: {project} ({project_id}) | Group: {group}")
    print("\n📊 Summary by Experiment:")
    print(format_summary(summarize(rows)))
    warnings = result.warnings + pairing_warnings(rows)
    not_ready = sum(1 for r in rows if r["comparison_ready"] != "1")
    if not_ready:
        warnings.append(f"{not_ready} row(s) have comparison_ready=0; see the comparison_warning column")
    for warning in warnings:
        print(f"⚠️  {warning}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ExportError as exc:
        print(f"❌ Export failed: {exc}", file=sys.stderr)
        sys.exit(1)
