"""Cisco SE Model Economics: read-only Experiment export to a flat CSV.

The data contract is documented in documentation/CISCO_SE_MODEL_ECONOMICS_CSV.md.
Every non-empty value comes from Splunk AO readback (Experiment, its tags,
root Traces and child Spans) or from the versioned local dataset plan
(domains/cisco_se/dataset_sources.yaml). Missing values stay empty; nothing is
estimated, defaulted to zero or recomputed from public price lists.

This module never runs an LLM, Experiment or Control and never writes to the
platform. The CLI wrapper is scripts/export-cisco-se-economics.
"""
from __future__ import annotations

import csv
import hashlib
import math
import os
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = 1
PAGE_SIZE = 100
MAX_PAGES = 10_000
DEFAULT_GT_PASS_THRESHOLD = 0.5
# Agent.process_query and the SDK row runner (process_row) error outputs.
AGENT_ERROR_PREFIXES = ("Error processing your request:", "error during executing")
CONTROL_MARKERS = (
    "blocked_by_agent_control",
    "steered_by_agent_control",
    "blocked by agent control",
    "adjusted by agent control",
)
GROUND_TRUTH_ALIASES = ("ground_truth_adherence", "ground truth adherence")
CONTEXT_ADHERENCE_ALIASES = ("context_adherence", "context adherence", "groundedness")
REQUIRED_RUNTIME_TAGS = ("application_model", "model_provider", "api_mode", "reasoning_effort")

FIELDS = [
    # Identity
    "schema_version",
    "exported_at_utc",
    "project_name",
    "project_id",
    "experiment_group_name",
    "experiment_group_id",
    "experiment_id",
    "experiment_name",
    "experiment_created_at_utc",
    "run_id",
    "code_version",
    # Model (application LLM only; Judge models are in judge_*)
    "application_model",
    "observed_llm_models",
    "model_provider",
    "api_mode",
    "reasoning_effort",
    # Dataset
    "dataset_id",
    "dataset_name",
    "dataset_version_index",
    "dataset_version",
    "dataset_hash",
    "scenario_id",
    "scenario_key",
    "scenario_input",
    "ground_truth",
    "generated_output",
    # Trace identity
    "trace_id",
    "session_id",
    "trace_created_at_utc",
    # Quality
    "ground_truth_adherence_metric_id",
    "ground_truth_adherence_status",
    "ground_truth_adherence_score",
    "ground_truth_adherence_pass",
    "ground_truth_adherence_scored",
    "ground_truth_adherence_pass_threshold",
    "ground_truth_adherence_rationale",
    "context_adherence_status",
    "context_adherence_score",
    "context_adherence_cost_usd",
    # Judge (Ground Truth Adherence judge; never mixed into application cost)
    "judge_model",
    "judge_count",
    "judge_input_tokens",
    "judge_output_tokens",
    "judge_cost_usd",
    # Efficiency (platform-computed root Trace metrics)
    "trace_duration_seconds",
    "trace_input_tokens",
    "trace_output_tokens",
    "trace_total_tokens",
    "token_source",
    "trace_cost_usd",
    "trace_cost_status",
    "llm_reasoning_tokens",
    "llm_cached_input_tokens",
    # Workflow (Single Agent span types)
    "span_count",
    "llm_call_count",
    "tool_call_count",
    "retriever_call_count",
    "control_span_count",
    "error_span_count",
    "unique_tools",
    # Trust
    "trace_status_code",
    "trace_complete",
    "agent_error",
    "control_intervention",
    "chaos_state",
    "quality_ready",
    "cost_ready",
    "comparison_ready",
    "comparison_warning",
]

INTEGER_FIELDS = {
    "schema_version", "dataset_version_index", "ground_truth_adherence_pass",
    "ground_truth_adherence_scored", "judge_count", "judge_input_tokens",
    "judge_output_tokens", "trace_input_tokens", "trace_output_tokens",
    "trace_total_tokens", "llm_reasoning_tokens", "llm_cached_input_tokens",
    "span_count", "llm_call_count", "tool_call_count", "retriever_call_count",
    "control_span_count", "error_span_count", "trace_status_code", "trace_complete",
    "agent_error", "control_intervention", "quality_ready", "cost_ready", "comparison_ready",
}
FLOAT_FIELDS = {
    "ground_truth_adherence_score", "ground_truth_adherence_pass_threshold",
    "context_adherence_score", "context_adherence_cost_usd", "judge_cost_usd",
    "trace_duration_seconds", "trace_cost_usd",
}
BINARY_FIELDS = {
    "ground_truth_adherence_pass", "ground_truth_adherence_scored", "trace_complete",
    "agent_error", "control_intervention", "quality_ready", "cost_ready", "comparison_ready",
}
REQUIRED_NON_EMPTY = ("schema_version", "exported_at_utc", "project_name", "experiment_id", "trace_id")


class ExportError(RuntimeError):
    """Raised when the export cannot produce a trustworthy CSV."""


# --------------------------------------------------------------------------- #
# Value helpers
# --------------------------------------------------------------------------- #

def is_unset(value: Any) -> bool:
    return value.__class__.__name__ == "Unset"


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def number(value: Any) -> Optional[float]:
    return value if is_number(value) else None


def integer(value: Any) -> Optional[int]:
    return int(value) if is_number(value) else None


def dict_value(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def to_plain(value: Any) -> Any:
    """attrs/pydantic SDK models -> plain dicts (records, experiments)."""
    if value is None or is_unset(value):
        return None
    if isinstance(value, dict):
        return value
    for attr in ("to_dict", "model_dump"):
        method = getattr(value, attr, None)
        if callable(method):
            return method()
    return value


def one_line(value: Any) -> str:
    """Escape backslash, CR/LF and tab so each CSV field stays on one physical line."""
    if value is None or is_unset(value):
        return ""
    text = str(value).replace("\\", "\\\\")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "\\n").replace("\t", "\\t")


def iso_utc(value: Any) -> str:
    if value is None or is_unset(value) or value == "":
        return ""
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def created_order(record: Dict[str, Any]) -> Tuple[datetime, str]:
    """Sort key: created_at as an aware datetime (missing sorts first), then id."""
    try:
        created = iso_utc(record.get("created_at"))
        moment = datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None
    except (TypeError, ValueError):
        moment = None
    return (moment or datetime.min.replace(tzinfo=timezone.utc), str(record.get("id") or ""))


def ns_to_seconds(value: Optional[float]) -> Optional[float]:
    return value / 1_000_000_000 if value is not None else None


def scenario_key(scenario_input: str) -> str:
    return hashlib.sha256(str(scenario_input or "").strip().encode("utf-8")).hexdigest()[:16]


def metric(record: Dict[str, Any], name: str) -> Optional[float]:
    return number(dict_value(record.get("metrics")).get(name))


def sum_optional(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _alias_matches(alias: str, candidates: Tuple[str, ...]) -> bool:
    folded = alias.strip().casefold()
    return any(folded == c or folded.startswith(c) for c in candidates)


def find_metric(record: Dict[str, Any], aliases: Tuple[str, ...]) -> Tuple[str, Dict[str, Any]]:
    """Return (metric_id, metric_info) for the first scorer whose alias matches."""
    matches = []
    for metric_id, raw in dict_value(record.get("metric_info")).items():
        info = dict_value(raw)
        if _alias_matches(str(info.get("metric_key_alias") or ""), aliases):
            matches.append((str(metric_id), info))
    matches.sort(key=lambda item: (str(item[1].get("metric_key_alias") or ""), item[0]))
    return matches[0] if matches else ("", {})


def flatten_numbers(value: Any) -> List[float]:
    if is_number(value):
        return [float(value)]
    if isinstance(value, (list, tuple)):
        result: List[float] = []
        for item in value:
            result.extend(flatten_numbers(item))
        return result
    return []


def metric_score(info: Dict[str, Any]) -> Optional[float]:
    """Multi-judge average when present, else the mean of numeric values."""
    average = number(info.get("multijudge_average"))
    if average is not None:
        return float(average)
    values = flatten_numbers(info.get("value"))
    return sum(values) / len(values) if values else None


def metric_status(info: Dict[str, Any]) -> str:
    return str(info.get("status_type") or info.get("status") or "").strip().lower()


def metric_tokens(info: Dict[str, Any], record: Dict[str, Any], alias: str, kind: str) -> Optional[int]:
    """Judge token counts from metric_info, falling back to the root metrics map."""
    tokens = dict_value(info.get("tokens"))
    value = tokens.get(kind) if tokens else info.get(kind)
    if value is None and alias:
        value = dict_value(record.get("metrics")).get(f"{alias}_{kind}")
    return integer(value)


def text_blob(record: Dict[str, Any]) -> str:
    return " ".join(str(record.get(k) or "") for k in ("input", "output", "error_message")).casefold()


def is_error_span(span: Dict[str, Any]) -> bool:
    status = number(span.get("status_code"))
    return bool(str(span.get("error_message") or "").strip()) or (status is not None and status >= 400)


def model_matches(observed: str, configured: str) -> bool:
    """OpenAI may return a dated snapshot (gpt-5-nano-2025-08-07) for an alias."""
    observed, configured = observed.strip().lower(), configured.strip().lower()
    return bool(configured) and (observed == configured or observed.startswith(configured + "-"))


# --------------------------------------------------------------------------- #
# Platform reads (retry + pagination)
# --------------------------------------------------------------------------- #

_TRANSIENT_MARKERS = (
    "timeout", "timed out", "connection reset", "connection refused", "429",
    "502", "503", "504", "rate limit", "too many requests", "temporarily unavailable",
    "server disconnected", "remote protocol", "upstream connect error",
)


def api_call(description: str, function: Callable[[], Any], *, attempts: int = 4,
             sleep: Callable[[float], None] = time.sleep) -> Any:
    """Bounded retry for transient/rate-limit errors; other errors raise immediately."""
    for attempt in range(1, attempts + 1):
        try:
            return function()
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}".casefold()
            if attempt == attempts or not any(m in text for m in _TRANSIENT_MARKERS):
                raise ExportError(f"{description} failed: {type(exc).__name__}: {exc}") from exc
            print(f"⚠️  {description}: transient error, retry {attempt + 1}/{attempts}", file=sys.stderr)
            sleep(2 * attempt)
    raise ExportError(f"{description}: retry loop ended unexpectedly")


def fetch_records(query: Callable[..., Any], description: str, *, page_size: int = PAGE_SIZE,
                  sleep: Callable[[float], None] = time.sleep) -> List[Dict[str, Any]]:
    """Read every page of a log-record query; de-duplicates records by id."""
    records: List[Dict[str, Any]] = []
    seen: set = set()
    token = 0
    for _ in range(MAX_PAGES):
        response = api_call(
            f"{description} (starting_token={token})",
            lambda: query(limit=page_size, starting_token=token),
            sleep=sleep,
        )
        if response is None or not hasattr(response, "records"):
            raise ExportError(f"{description}: the platform returned an empty response")
        raw = getattr(response, "records")
        batch = [] if raw is None or is_unset(raw) else list(raw)
        new = 0
        for item in batch:
            values = to_plain(item) or {}
            record_id = str(values.get("id") or "")
            if record_id and record_id in seen:
                continue
            if record_id:
                seen.add(record_id)
            records.append(values)
            new += 1
        next_token = getattr(response, "next_starting_token", None)
        if next_token is not None and not is_unset(next_token):
            next_value = int(next_token)
            if next_value <= token:
                break
            token = next_value
            continue
        if len(batch) < page_size:
            break
        if new == 0:
            raise ExportError(f"{description}: pagination made no progress; stopped")
        token += len(batch)
    else:
        raise ExportError(f"{description}: more than {MAX_PAGES} pages")
    return records


# --------------------------------------------------------------------------- #
# Row building
# --------------------------------------------------------------------------- #

@dataclass
class DatasetPlan:
    """The versioned local dataset plan (domains/cisco_se/dataset_sources.yaml)."""
    dataset_version: str
    dataset_hash: str
    scenario_ids: Dict[str, str]  # scenario_key -> question id

    @classmethod
    def from_yaml(cls, data: Dict[str, Any]) -> "DatasetPlan":
        return cls(
            dataset_version=str(data.get("dataset_version") or ""),
            dataset_hash=str(data.get("dataset_hash") or ""),
            scenario_ids={str(q["scenario_key"]): str(q["id"]) for q in data.get("questions") or []},
        )


@dataclass
class ExperimentData:
    experiment: Dict[str, Any]
    tags: Dict[str, str]
    traces: List[Dict[str, Any]]
    spans: List[Dict[str, Any]]


@dataclass
class ExportResult:
    rows: List[Dict[str, Any]]
    warnings: List[str] = field(default_factory=list)


def build_rows(
    *,
    project_name: str,
    project_id: str,
    experiments: List[ExperimentData],
    plan: DatasetPlan,
    exported_at: str,
    gt_pass_threshold: float = DEFAULT_GT_PASS_THRESHOLD,
) -> ExportResult:
    """One CSV row per root Trace (unique key: experiment_id + trace_id)."""
    rows: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for data in experiments:
        exp = data.experiment
        tags = data.tags
        experiment_id = str(exp.get("id") or "")
        experiment_name = str(exp.get("name") or "")
        dataset = dict_value(exp.get("dataset"))
        application_model = tags.get("application_model", "")
        missing_tags = [t for t in REQUIRED_RUNTIME_TAGS if not tags.get(t)]
        if missing_tags:
            warnings.append(f"Experiment {experiment_name!r} is missing runtime tags: {', '.join(missing_tags)}")
        if tags.get("dataset_hash") and tags.get("dataset_hash") != plan.dataset_hash:
            warnings.append(f"Experiment {experiment_name!r} dataset_hash differs from the local dataset plan")

        spans_by_trace: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for span in data.spans:
            spans_by_trace[str(span.get("trace_id") or "")].append(span)
        trace_ids = {str(t.get("trace_id") or t.get("id") or "") for t in data.traces}
        orphans = sum(1 for tid in spans_by_trace if tid not in trace_ids)
        if orphans:
            warnings.append(f"Experiment {experiment_name!r} has spans for {orphans} trace(s) not returned as root traces")

        seen_trace_ids: set = set()
        scenario_counts = Counter()
        traces = sorted(data.traces, key=lambda t: (iso_utc(t.get("created_at")), str(t.get("id") or "")))
        for root in traces:
            trace_id = str(root.get("trace_id") or root.get("id") or "")
            if trace_id in seen_trace_ids:
                warnings.append(f"Experiment {experiment_name!r} returned trace {trace_id} more than once; kept the first")
                continue
            seen_trace_ids.add(trace_id)
            row = _trace_row(
                root=root,
                spans=spans_by_trace.get(trace_id, []),
                exp=exp,
                dataset=dataset,
                tags=tags,
                application_model=application_model,
                missing_tags=missing_tags,
                plan=plan,
                project_name=project_name,
                project_id=project_id,
                exported_at=exported_at,
                gt_pass_threshold=gt_pass_threshold,
            )
            scenario_counts[row["scenario_key"]] += 1
            rows.append(row)

        duplicates = {k for k, n in scenario_counts.items() if n > 1}
        for row in rows:
            if row["experiment_id"] == experiment_id and row["scenario_key"] in duplicates:
                _add_warning(row, "duplicate_scenario_in_experiment")
                row["comparison_ready"] = 0
        missing = set(plan.scenario_ids) - set(scenario_counts)
        if missing:
            ids = sorted(plan.scenario_ids[k] for k in missing)
            warnings.append(f"Experiment {experiment_name!r} has no trace for planned questions: {', '.join(ids)}")
    return ExportResult(rows=rows, warnings=warnings)


def _add_warning(row: Dict[str, Any], warning: str) -> None:
    current = [w for w in str(row.get("comparison_warning") or "").split(";") if w]
    if warning not in current:
        current.append(warning)
    row["comparison_warning"] = ";".join(current)


def _trace_row(*, root, spans, exp, dataset, tags, application_model, missing_tags, plan,
               project_name, project_id, exported_at, gt_pass_threshold) -> Dict[str, Any]:
    warnings: List[str] = []
    llm_spans = [s for s in spans if s.get("type") == "llm"]
    tool_spans = [s for s in spans if s.get("type") == "tool"]
    retriever_spans = [s for s in spans if s.get("type") == "retriever"]
    control_spans = [s for s in spans if s.get("type") == "control"]
    error_spans = [s for s in spans if is_error_span(s)]

    observed_models = sorted({str(s.get("model")) for s in llm_spans if s.get("model")})
    model_ok = bool(observed_models) and bool(application_model) and all(
        model_matches(m, application_model) for m in observed_models
    )
    if not observed_models:
        warnings.append("no_llm_model_observed")
    elif not model_ok:
        warnings.append("application_model_mismatch")

    scenario_input = str(root.get("dataset_input") or root.get("input") or "")
    ground_truth = str(root.get("dataset_output") or "")
    generated_output = str(root.get("output") or "")
    key = scenario_key(scenario_input)
    scenario_id = plan.scenario_ids.get(key, "")
    if not scenario_id:
        warnings.append("scenario_not_in_dataset_plan")
    agent_error = int(generated_output.strip().startswith(AGENT_ERROR_PREFIXES))
    if agent_error:
        warnings.append("agent_error_output")
    control_intervention = int(any(
        marker in text_blob(record) for record in [root, *spans] for marker in CONTROL_MARKERS
    ))
    if control_intervention:
        warnings.append("agent_control_intervened")
    chaos = tags.get("chaos_state", "")
    if chaos != "off":
        warnings.append("chaos_not_off" if chaos else "chaos_state_unknown")

    # Ground Truth Adherence (core Judge)
    gt_id, gt_info = find_metric(root, GROUND_TRUTH_ALIASES)
    gt_alias = str(gt_info.get("metric_key_alias") or "")
    gt_status = metric_status(gt_info)
    gt_score = metric_score(gt_info) if gt_status in ("", "success") else None
    gt_scored = int(gt_status == "success" and gt_score is not None)
    gt_pass: Any = int(gt_score >= gt_pass_threshold) if gt_scored else ""
    if not gt_info:
        warnings.append("ground_truth_adherence_missing")
    elif not gt_scored:
        warnings.append(f"ground_truth_adherence_{gt_status or 'not_scored'}")

    # Context Adherence: a numeric trace value wins. The platform usually only
    # marks the root as roll_up, so the score comes from the final-answer LLM
    # span. Earlier LLM spans are tool-call decisions without an answer, which
    # judges score inconsistently, so they are excluded from the score; their
    # Judge cost is still included in context_adherence_cost_usd.
    _, ca_info = find_metric(root, CONTEXT_ADHERENCE_ALIASES)
    ca_status = metric_status(ca_info)
    ca_score = metric_score(ca_info) if ca_info and ca_status in ("", "success") else None
    ca_cost = number(ca_info.get("cost")) if ca_info else None
    if ca_score is None and llm_spans:
        span_infos = [find_metric(s, CONTEXT_ADHERENCE_ALIASES)[1] for s in llm_spans]
        final_info = find_metric(max(llm_spans, key=created_order), CONTEXT_ADHERENCE_ALIASES)[1]
        if final_info:
            final_status = metric_status(final_info)
            ca_score = metric_score(final_info) if final_status in ("", "success") else None
            ca_status = final_status or ("success" if ca_score is not None else "not_scored")
        elif ca_info:
            ca_status = "final_llm_not_scored"
        if any(span_infos):
            ca_cost = sum_optional(number(i.get("cost")) for i in span_infos if i)
    if ca_score is None:
        warnings.append(f"context_adherence_{ca_status or 'missing'}")

    duration = ns_to_seconds(metric(root, "duration_ns"))
    cost = metric(root, "cost")
    cost_status = str(dict_value(root.get("metrics")).get("cost_status") or "")
    token_keys = ("num_input_tokens", "num_output_tokens", "num_total_tokens")
    in_tok, out_tok, total_tok = (integer(metric(root, k)) for k in token_keys)
    token_source = "trace" if None not in (in_tok, out_tok, total_tok) else ""
    if not token_source and llm_spans:
        # Root traces logged without reliable ingest carry no token roll-up;
        # the child LLM spans still hold the platform-recorded usage.
        span_tokens = [sum_optional(integer(metric(s, k)) for s in llm_spans) for k in token_keys]
        if all(v is not None for v in span_tokens):
            in_tok, out_tok, total_tok = (int(v) for v in span_tokens)
            token_source = "llm_spans"
    reasoning = sum_optional(integer(metric(s, "num_reasoning_tokens")) for s in llm_spans)
    cached = sum_optional(integer(metric(s, "num_cached_input_tokens")) for s in llm_spans)
    cost_zero_with_tokens = cost == 0 and bool(total_tok)
    cost_ready = int(
        all(v is not None for v in (duration, cost, in_tok, out_tok, total_tok)) and not cost_zero_with_tokens
    )
    if cost is None:
        warnings.append("trace_cost_missing")
    elif cost_zero_with_tokens:
        warnings.append("platform_cost_zero_with_tokens")
    elif not cost_ready:
        warnings.append("trace_tokens_or_duration_missing")

    status_code = integer(root.get("status_code"))
    # The SDK leaves root Trace status_code unset (0); only real HTTP-style
    # error codes make a Trace unusable.
    status_ok = status_code in (None, 0) or 200 <= status_code < 400
    complete = bool(root.get("is_complete"))
    if not complete:
        warnings.append("trace_incomplete")
    if not status_ok:
        warnings.append(f"trace_status_{status_code}")
    if error_spans:
        warnings.append("error_spans")
    if not spans:
        warnings.append("no_child_spans")
    if not (scenario_input.strip() and ground_truth.strip() and generated_output.strip()):
        warnings.append("missing_input_output_or_ground_truth")
    if missing_tags:
        warnings.append("missing_runtime_tags")
    dataset_ok = tags.get("dataset_hash") == plan.dataset_hash and tags.get("dataset_version") == plan.dataset_version
    if not dataset_ok:
        warnings.append("dataset_not_in_plan")

    quality_ready = gt_scored
    comparison_ready = int(all((
        complete, status_ok, not error_spans, bool(spans), bool(llm_spans),
        bool(scenario_input.strip()), bool(ground_truth.strip()), bool(generated_output.strip()),
        not agent_error, not control_intervention, chaos == "off",
        model_ok, not missing_tags, dataset_ok, bool(scenario_id),
        bool(cost_ready), bool(quality_ready),
    )))
    root_metrics = dict_value(root.get("metrics"))
    judge_cost = number(gt_info.get("cost"))
    if judge_cost is None and gt_alias:
        judge_cost = number(root_metrics.get(f"{gt_alias}_metric_cost"))
    tools = sorted({str(s.get("name") or "") for s in tool_spans if s.get("name")})
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at_utc": exported_at,
        "project_name": one_line(project_name),
        "project_id": project_id,
        "experiment_group_name": one_line(exp.get("experiment_group_name")),
        "experiment_group_id": one_line(exp.get("experiment_group_id")),
        "experiment_id": str(exp.get("id") or ""),
        "experiment_name": one_line(exp.get("name")),
        "experiment_created_at_utc": iso_utc(exp.get("created_at")),
        "run_id": one_line(tags.get("run_id")),
        "code_version": one_line(tags.get("code_version")),
        "application_model": one_line(application_model),
        "observed_llm_models": one_line(";".join(observed_models)),
        "model_provider": one_line(tags.get("model_provider")),
        "api_mode": one_line(tags.get("api_mode")),
        "reasoning_effort": one_line(tags.get("reasoning_effort")),
        "dataset_id": one_line(dataset.get("dataset_id")),
        "dataset_name": one_line(dataset.get("name")),
        "dataset_version_index": integer(dataset.get("version_index")),
        "dataset_version": one_line(tags.get("dataset_version")),
        "dataset_hash": one_line(tags.get("dataset_hash")),
        "scenario_id": scenario_id,
        "scenario_key": key,
        "scenario_input": one_line(scenario_input),
        "ground_truth": one_line(ground_truth),
        "generated_output": one_line(generated_output),
        "trace_id": trace_id_of(root),
        "session_id": one_line(root.get("session_id")),
        "trace_created_at_utc": iso_utc(root.get("created_at")),
        "ground_truth_adherence_metric_id": gt_id,
        "ground_truth_adherence_status": one_line(gt_status),
        "ground_truth_adherence_score": gt_score if gt_scored else None,
        "ground_truth_adherence_pass": gt_pass,
        "ground_truth_adherence_scored": gt_scored,
        "ground_truth_adherence_pass_threshold": gt_pass_threshold,
        "ground_truth_adherence_rationale": one_line(gt_info.get("rationale")),
        "context_adherence_status": one_line(ca_status),
        "context_adherence_score": ca_score,
        "context_adherence_cost_usd": ca_cost,
        "judge_model": one_line(gt_info.get("model_alias") or (root_metrics.get(f"{gt_alias}_model_alias") if gt_alias else "")),
        "judge_count": integer(gt_info.get("num_judges") or (root_metrics.get(f"{gt_alias}_num_judges") if gt_alias else None)),
        "judge_input_tokens": metric_tokens(gt_info, root, gt_alias, "input_tokens"),
        "judge_output_tokens": metric_tokens(gt_info, root, gt_alias, "output_tokens"),
        "judge_cost_usd": judge_cost,
        "trace_duration_seconds": duration,
        "trace_input_tokens": in_tok,
        "trace_output_tokens": out_tok,
        "trace_total_tokens": total_tok,
        "token_source": token_source,
        "trace_cost_usd": cost,
        "trace_cost_status": one_line(cost_status),
        "llm_reasoning_tokens": reasoning,
        "llm_cached_input_tokens": cached,
        "span_count": len(spans),
        "llm_call_count": len(llm_spans),
        "tool_call_count": len(tool_spans),
        "retriever_call_count": len(retriever_spans),
        "control_span_count": len(control_spans),
        "error_span_count": len(error_spans),
        "unique_tools": one_line(";".join(tools)),
        "trace_status_code": status_code,
        "trace_complete": int(complete),
        "agent_error": agent_error,
        "control_intervention": control_intervention,
        "chaos_state": one_line(chaos),
        "quality_ready": quality_ready,
        "cost_ready": cost_ready,
        "comparison_ready": comparison_ready,
        "comparison_warning": ";".join(dict.fromkeys(warnings)),
    }


def trace_id_of(record: Dict[str, Any]) -> str:
    return str(record.get("trace_id") or record.get("id") or "")


# --------------------------------------------------------------------------- #
# Writing and validation
# --------------------------------------------------------------------------- #

def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return value


def validate_csv(path: str) -> List[Dict[str, str]]:
    """Read the CSV back and check header, types, uniqueness and readiness rules."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != FIELDS:
            raise ExportError("CSV header does not match the data contract")
        rows = list(reader)
    keys = set()
    for index, row in enumerate(rows, start=2):
        for name in REQUIRED_NON_EMPTY:
            if not row[name]:
                raise ExportError(f"line {index}: {name} is empty")
        key = (row["experiment_id"], row["trace_id"])
        if key in keys:
            raise ExportError(f"line {index}: duplicate (experiment_id, trace_id) {key}")
        keys.add(key)
        for name in INTEGER_FIELDS:
            if row[name] != "":
                try:
                    int(row[name])
                except ValueError as exc:
                    raise ExportError(f"line {index}: {name} is not an integer") from exc
        for name in FLOAT_FIELDS:
            if row[name] != "":
                try:
                    if not math.isfinite(float(row[name])):
                        raise ValueError
                except ValueError as exc:
                    raise ExportError(f"line {index}: {name} is not a finite number") from exc
        for name in BINARY_FIELDS:
            if row[name] not in ("", "0", "1"):
                raise ExportError(f"line {index}: {name} must be 0, 1 or empty")
        if row["token_source"] not in ("", "trace", "llm_spans"):
            raise ExportError(f"line {index}: invalid token_source value")
        if any("\n" in v or "\r" in v for v in row.values()):
            raise ExportError(f"line {index}: unescaped line break")
        if row["comparison_ready"] == "1" and (
            row["trace_cost_usd"] == "" or row["ground_truth_adherence_scored"] != "1"
            or row["cost_ready"] != "1" or row["quality_ready"] != "1"
        ):
            raise ExportError(f"line {index}: comparison_ready=1 without cost or quality data")
    return rows


def write_csv_atomic(rows: List[Dict[str, Any]], output_path: str) -> List[Dict[str, str]]:
    """Write to a temp file in the target directory, validate, then os.replace.

    A failed write or validation leaves any previous CSV untouched.
    """
    directory = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".cisco_se_export_", suffix=".csv.tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="raise", lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _csv_value(row.get(k)) for k in FIELDS})
        validated = validate_csv(tmp_path)
        if len(validated) != len(rows):
            raise ExportError("CSV read-back row count differs from the rows written")
        os.replace(tmp_path, output_path)
        return validated
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# --------------------------------------------------------------------------- #
# Summary and pairing
# --------------------------------------------------------------------------- #

def _floats(rows: List[Dict[str, str]], name: str) -> List[float]:
    return [float(r[name]) for r in rows if r[name] != ""]


def p95(values: List[float]) -> Optional[float]:
    """Nearest-rank P95."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _sum(rows: List[Dict[str, str]], name: str) -> Optional[float]:
    values = _floats(rows, name)
    return sum(values) if values else None


def summarize(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Per-Experiment summary (never merges Experiments of the same model).

    Valid samples are rows with comparison_ready=1. Cost, tokens, latency and
    cost per passing answer use valid samples only; GT pass rate uses every
    successfully scored row (sum(pass) / sum(scored)). observed_* totals cover
    every exported row so failed or unscored Traces are not hidden.
    """
    by_experiment: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_experiment[row["experiment_id"]].append(row)
    summary = []
    for experiment_id, items in by_experiment.items():
        ready = [r for r in items if r["comparison_ready"] == "1"]
        scored_rows = [r for r in items if r["ground_truth_adherence_scored"] == "1"]
        scored = len(scored_rows)
        passed = sum(int(r["ground_truth_adherence_pass"] or 0) for r in scored_rows)
        valid_cost = _sum(ready, "trace_cost_usd")
        valid_pass = sum(int(r["ground_truth_adherence_pass"] or 0) for r in ready)
        durations = _floats(ready, "trace_duration_seconds")
        valid_tokens = _sum(ready, "trace_total_tokens")
        summary.append({
            "experiment_id": experiment_id,
            "experiment_name": items[0]["experiment_name"],
            "application_model": items[0]["application_model"],
            "rows": len(items),
            "comparison_ready_rows": len(ready),
            "gt_scored": scored,
            "gt_passed": passed,
            "gt_pass_rate": passed / scored if scored else None,
            "app_cost_usd": valid_cost,
            "observed_app_cost_usd": _sum(items, "trace_cost_usd"),
            "judge_cost_usd": _sum(items, "judge_cost_usd"),
            "context_adherence_cost_usd": _sum(items, "context_adherence_cost_usd"),
            "total_tokens": int(valid_tokens) if valid_tokens is not None else None,
            "observed_total_tokens": int(_sum(items, "trace_total_tokens") or 0) if _floats(items, "trace_total_tokens") else None,
            "avg_latency_s": statistics.fmean(durations) if durations else None,
            "p95_latency_s": p95(durations),
            "cost_per_passing_answer_usd": (valid_cost / valid_pass) if valid_cost is not None and valid_pass else None,
        })
    return summary


def pairing_warnings(rows: List[Dict[str, str]]) -> List[str]:
    """Cross-model checks: same dataset identity and the same scenario keys."""
    warnings = []
    experiments = {r["experiment_id"]: r for r in rows}
    identities = {(r["dataset_id"], r["dataset_version_index"], r["dataset_hash"]) for r in experiments.values()}
    if len(identities) > 1:
        warnings.append("Experiments differ in dataset_id/dataset_version_index/dataset_hash; they cannot be paired")
    models = defaultdict(set)
    for r in experiments.values():
        models[r["application_model"]].add(r["experiment_id"])
    if len(models) < 2:
        warnings.append("Fewer than two application models exported; no paired comparison")
    scenarios = defaultdict(set)
    for r in rows:
        if r["comparison_ready"] == "1":
            scenarios[r["scenario_key"]].add(r["application_model"])
    unpaired = [k for k, m in scenarios.items() if len(m) < len(models)]
    if len(models) >= 2 and unpaired:
        warnings.append(f"{len(unpaired)} question(s) are comparison_ready=1 for only some models")
    return warnings


def format_summary(summary: List[Dict[str, Any]]) -> str:
    def fmt(value: Any, spec: str = "") -> str:
        if value is None:
            return "n/a"
        return format(value, spec) if spec else str(value)

    lines = []
    for s in summary:
        lines.append(
            f"- Model {s['application_model'] or '?'} | {s['experiment_name']} ({s['experiment_id']})\n"
            f"    rows={s['rows']}  comparison_ready={s['comparison_ready_rows']}  "
            f"GT pass={s['gt_passed']}/{s['gt_scored']} ({fmt(s['gt_pass_rate'], '.0%')})\n"
            f"    ready rows: app cost USD={fmt(s['app_cost_usd'], '.6f')}  total tokens={fmt(s['total_tokens'])}  "
            f"cost per passing answer USD={fmt(s['cost_per_passing_answer_usd'], '.6f')}\n"
            f"    all rows: app cost USD={fmt(s['observed_app_cost_usd'], '.6f')}  total tokens={fmt(s['observed_total_tokens'])}\n"
            f"    scoring cost (not in app cost): GT judge USD={fmt(s['judge_cost_usd'], '.6f')}  "
            f"Context Adherence USD={fmt(s['context_adherence_cost_usd'], '.6f')}\n"
            f"    ready rows: avg latency s={fmt(s['avg_latency_s'], '.2f')}  P95 latency s={fmt(s['p95_latency_s'], '.2f')}"
        )
    return "\n".join(lines)
