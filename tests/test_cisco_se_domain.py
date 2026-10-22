"""Cisco SE domain, hosted adapter, ingest/compat shims and CSV exporter.

Mock-only: no LLM, Splunk AO or database calls. Cloud acceptance (real
Experiments, Judge scores, platform cost) is recorded in
documentation/VALIDATION.md, not asserted here.
"""
import asyncio
import csv
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from pydantic import BaseModel

from domain_manager import DomainManager
from experiments import cisco_se_economics as econ
from experiments.experiment_helpers import (
    dataset_content_hash,
    experiment_runtime_tags,
    local_dataset_records,
    read_dataset_csv,
    scenario_key,
)
from helpers import galileo_compat, galileo_ingest
from helpers.llm_utils import get_chat_model, get_model_runtime_options, validate_reasoning_effort

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIR = ROOT / "domains" / "cisco_se"
PLAN_DATA = yaml.safe_load((DOMAIN_DIR / "dataset_sources.yaml").read_text(encoding="utf-8"))
PLAN = econ.DatasetPlan.from_yaml(PLAN_DATA)


class CiscoSeDomainContractTests(unittest.TestCase):
    def setUp(self):
        self.cfg = DomainManager().load_domain_config("cisco_se")

    def test_domain_is_read_only_rag_with_strict_hosted_index(self):
        config = self.cfg.config
        self.assertEqual(config["tools"], ["search_cisco_se_specs"])
        self.assertEqual(config["rag"]["mode"], "documents")
        self.assertFalse(config["rag"]["generic_tool"])
        self.assertTrue(config["vectorstore"]["strict_index"])
        self.assertEqual(config["vectorstore"]["provider"], "hosted")
        self.assertEqual(config["model"]["providers"], ["hosted"])
        self.assertEqual(config["experiments"]["group"], "Cisco SE Model Economics")
        self.assertEqual(config["experiments"]["dataset_version"], PLAN.dataset_version)
        self.assertTrue(config["galileo"]["reliable_ingest"])

    def test_dataset_hash_and_scenario_keys_match_plan(self):
        records = local_dataset_records(str(DOMAIN_DIR / "dataset.csv"))
        self.assertEqual(len(records), 10)
        self.assertEqual(dataset_content_hash(records), PLAN.dataset_hash)
        keys = {scenario_key(i): hashlib.sha256(i.strip().encode("utf-8")).hexdigest() for i, _ in records}
        self.assertEqual(set(keys), set(PLAN.scenario_ids))
        for question in PLAN_DATA["questions"]:
            self.assertEqual(keys[question["scenario_key"]], question["input_sha256"])
            self.assertTrue(question["fact_ids"])
            self.assertTrue(all(s["url"].startswith("https://www.") for s in question["sources"]))

    def test_dataset_facts_exist_in_knowledge_base_with_official_sources(self):
        with open(DOMAIN_DIR / "docs" / "qa.csv", newline="", encoding="utf-8") as handle:
            facts = {row["fact_id"]: row for row in csv.DictReader(handle)}
        self.assertEqual({f["vendor"] for f in facts.values()}, {"Cisco", "H3C"})
        for question in PLAN_DATA["questions"]:
            for fact_id in question["fact_ids"]:
                self.assertIn(fact_id, facts)
        for fact in facts.values():
            self.assertTrue(fact["source_url"].startswith(("https://www.cisco.com/", "https://www.h3c.com/")))
            self.assertTrue(fact["value"].strip() and fact["source_section"].strip())

    def test_hosted_models_use_responses_api_without_temperature(self):
        model_cfg = self.cfg.config["model"]
        for model in ("gpt-5-nano", "gpt-6.1-sol"):
            options = get_model_runtime_options(model_cfg, model, "hosted")
            self.assertEqual(options, {"reasoning_effort": "low", "use_responses_api": True})
            with patch("helpers.llm_utils.ensure_openai_api_key"), patch("langchain_openai.ChatOpenAI") as chat:
                get_chat_model(model, provider="hosted", **options)
            kwargs = chat.call_args.kwargs
            self.assertEqual((kwargs["model"], kwargs["use_responses_api"], kwargs["reasoning_effort"]),
                             (model, True, "low"))
            self.assertNotIn("temperature", kwargs)
            self.assertNotIn("top_p", kwargs)
        tags = experiment_runtime_tags(self.cfg.config, "gpt-6.1-sol", "hosted")
        self.assertEqual(tags, {"application_model": "gpt-6.1-sol", "model_provider": "openai",
                                "api_mode": "responses", "reasoning_effort": "low"})
        with self.assertRaises(ValueError):
            validate_reasoning_effort("gpt-6.1-sol", "none")

    def test_healthcare_runtime_and_ingest_are_unchanged(self):
        healthcare = DomainManager().load_domain_config("healthcare").config
        model = healthcare["model"].get("hosted_default_model")
        self.assertEqual(get_model_runtime_options(healthcare["model"], model, "hosted"), {})
        self.assertFalse(galileo_ingest.reliable_ingest_requested(healthcare))
        self.assertFalse(galileo_ingest.apply_domain_reliable_ingest(healthcare, "healthcare-project-id"))
        self.assertFalse(galileo_ingest.is_reliable_ingest_enabled("healthcare-project-id"))


class _FakeIngestRequest(BaseModel):
    reliable: bool = False
    note: str = ""


class ReliableIngestTests(unittest.TestCase):
    def setUp(self):
        self.ids = patch.object(galileo_ingest, "_RELIABLE_PROJECT_IDS", set())
        self.ids.start()
        self.addCleanup(self.ids.stop)

    def _client_class(self, received):
        class FakeTraces:
            def __init__(self, project_id):
                self.project_id = project_id

            async def ingest_traces(self, request):
                received.append(request)
                return "sent"

        return FakeTraces

    def test_only_registered_projects_are_sent_reliable(self):
        received = []
        cls = self._client_class(received)
        galileo_ingest._wrap_client(cls)
        galileo_ingest._wrap_client(cls)  # idempotent: no double wrapping
        galileo_ingest._RELIABLE_PROJECT_IDS.add("cisco-project")
        original = _FakeIngestRequest(note="x")
        self.assertEqual(asyncio.run(cls("cisco-project").ingest_traces(original)), "sent")
        asyncio.run(cls("other-project").ingest_traces(original))
        asyncio.run(cls(None).ingest_traces(original))
        self.assertEqual(len(received), 3)
        self.assertTrue(received[0].reliable)
        self.assertEqual(received[0].note, "x")
        self.assertFalse(original.reliable)
        self.assertIs(received[1], original)
        self.assertIs(received[2], original)

    def test_enable_wraps_sdk_clients_once_and_gates_by_config(self):
        from galileo.traces import IngestTraces, Traces

        self.assertFalse(galileo_ingest.enable_reliable_ingest(None))
        self.assertTrue(galileo_ingest.enable_reliable_ingest("p1"))
        first = Traces.ingest_traces
        self.assertTrue(galileo_ingest.enable_reliable_ingest("p1"))
        self.assertIs(Traces.ingest_traces, first)
        self.assertTrue(getattr(Traces.ingest_traces, galileo_ingest._PATCHED_ATTR))
        self.assertTrue(getattr(IngestTraces.ingest_traces, galileo_ingest._PATCHED_ATTR))
        self.assertTrue(galileo_ingest.is_reliable_ingest_enabled("p1"))
        self.assertFalse(galileo_ingest.is_reliable_ingest_enabled("p2"))
        opted_in = {"galileo": {"reliable_ingest": True}}
        self.assertTrue(galileo_ingest.apply_domain_reliable_ingest(opted_in, "p2"))
        self.assertFalse(galileo_ingest.apply_domain_reliable_ingest({"galileo": {}}, "p3"))
        self.assertFalse(galileo_ingest.apply_domain_reliable_ingest(opted_in, None))
        self.assertEqual(galileo_ingest._RELIABLE_PROJECT_IDS, {"p1", "p2"})


class PermissionCompatTests(unittest.TestCase):
    def test_unknown_permission_action_is_kept_and_known_actions_unchanged(self):
        from galileo.resources.models.permission import Permission
        from galileo.resources.models.project_action import ProjectAction

        self.assertTrue(galileo_compat.tolerate_unknown_permission_actions())
        self.assertTrue(galileo_compat.tolerate_unknown_permission_actions())
        unknown = Permission.from_dict({"action": "configure_rate_limit", "allowed": True})
        self.assertEqual(str(unknown.action), "configure_rate_limit")
        self.assertIsInstance(unknown.action, galileo_compat.UnknownPermissionAction)
        self.assertEqual(unknown.to_dict()["action"], "configure_rate_limit")
        known = Permission.from_dict({"action": "share", "allowed": False})
        self.assertIsInstance(known.action, ProjectAction)
        self.assertFalse(known.allowed)
        with self.assertRaises(Exception):
            Permission.from_dict({"action": "share"})


# --------------------------------------------------------------------------- #
# Exporter fixtures
# --------------------------------------------------------------------------- #

QUESTIONS = read_dataset_csv(str(DOMAIN_DIR / "dataset.csv"))
TAGS = {
    "application_model": "gpt-5-nano", "model_provider": "openai", "api_mode": "responses",
    "reasoning_effort": "low", "dataset_hash": PLAN.dataset_hash, "dataset_version": PLAN.dataset_version,
    "code_version": "abc-dirty", "chaos_state": "off", "run_id": "R1",
}


def experiment(exp_id="E1", name="Cisco SE Model Economics - gpt-5-nano - R1"):
    return {
        "id": exp_id, "name": name, "created_at": "2026-10-21T07:10:00+00:00",
        "experiment_group_name": "Cisco SE Model Economics", "experiment_group_id": "G1",
        "dataset": {"dataset_id": "D1", "name": "Cisco SE ds", "version_index": 1},
    }


def root_trace(trace_id="T1", question=0, *, cost=0.0002, tokens=(1500, 300, 1800), gt="success",
               gt_value=1.0, status_code=0, output="The N9332D-H2R has 32 x 400G QSFP-DD ports."):
    metrics = {"duration_ns": 4_000_000_000, "cost": cost, "cost_status": "success",
               "ground_truth_adherence_metric_cost": 0.001}
    if tokens:
        metrics.update(dict(zip(("num_input_tokens", "num_output_tokens", "num_total_tokens"),
                                (float(t) for t in tokens))))
    return {
        "id": trace_id, "trace_id": trace_id, "type": "trace", "created_at": "2026-10-21T07:11:00Z",
        "dataset_input": QUESTIONS[question]["input"], "dataset_output": QUESTIONS[question]["output"],
        "input": QUESTIONS[question]["input"], "output": output, "is_complete": True,
        "status_code": status_code, "session_id": "S1", "metrics": metrics,
        "metric_info": {
            "gt-1": {"metric_key_alias": "ground_truth_adherence", "status_type": gt, "value": gt_value,
                     "rationale": "matches\nfacts", "model_alias": "gpt-4.1-mini", "num_judges": 3},
            "ca-1": {"metric_key_alias": "context_adherence", "status_type": "success", "value": 0.9,
                     "cost": 0.0004},
        },
    }


def child_spans(trace_id="T1", model="gpt-5-nano-2025-08-07", tokens=(1500, 300, 1800)):
    llm = {"id": f"{trace_id}-llm", "trace_id": trace_id, "type": "llm", "model": model,
           "metrics": dict(zip(("num_input_tokens", "num_output_tokens", "num_total_tokens"), tokens))}
    return [
        llm,
        {"id": f"{trace_id}-tool", "trace_id": trace_id, "type": "tool", "name": "search_cisco_se_specs",
         "metrics": {}},
        {"id": f"{trace_id}-ret", "trace_id": trace_id, "type": "retriever", "name": "VectorStoreRetriever",
         "metrics": {}},
    ]


def build(traces, spans, tags=None, exp=None):
    data = econ.ExperimentData(experiment=exp or experiment(), tags=dict(tags or TAGS), traces=traces, spans=spans)
    return econ.build_rows(project_name="splunk-ao-golden-demo-cisco-se", project_id="P1",
                           experiments=[data], plan=PLAN, exported_at="2026-10-21T08:00:00Z")


class Page:
    def __init__(self, records, next_token=None):
        self.records = records
        self.next_starting_token = next_token


class ExporterReadTests(unittest.TestCase):
    def test_fetch_records_follows_tokens_and_dedups(self):
        pages = {0: Page([{"id": "a"}, {"id": "b"}], 2), 2: Page([{"id": "b"}, {"id": "c"}], 4), 4: Page([], None)}
        calls = []

        def query(limit, starting_token):
            calls.append(starting_token)
            return pages[starting_token]

        records = econ.fetch_records(query, "traces", page_size=2, sleep=lambda _s: None)
        self.assertEqual([r["id"] for r in records], ["a", "b", "c"])
        self.assertEqual(calls, [0, 2, 4])

    def test_fetch_records_offsets_without_token_and_rejects_bad_responses(self):
        data = [{"id": str(i)} for i in range(5)]
        records = econ.fetch_records(lambda limit, starting_token: Page(data[starting_token:starting_token + limit]),
                                     "spans", page_size=2)
        self.assertEqual(len(records), 5)
        with self.assertRaises(econ.ExportError):
            econ.fetch_records(lambda **_: None, "spans")
        with self.assertRaises(econ.ExportError):
            econ.fetch_records(lambda **_: Page([{"id": "same"}, {"id": "same"}]), "spans", page_size=2)

    def test_api_call_retries_transient_errors_only(self):
        attempts = MagicMock(side_effect=[RuntimeError("503 Service Unavailable"), "ok"])
        sleeps = []
        self.assertEqual(econ.api_call("read", attempts, sleep=sleeps.append), "ok")
        self.assertEqual(sleeps, [2])
        permanent = MagicMock(side_effect=ValueError("bad request"))
        with self.assertRaises(econ.ExportError):
            econ.api_call("read", permanent, sleep=sleeps.append)
        self.assertEqual(permanent.call_count, 1)
        always = MagicMock(side_effect=RuntimeError("429 rate limit"))
        with self.assertRaises(econ.ExportError):
            econ.api_call("read", always, attempts=3, sleep=lambda _s: None)
        self.assertEqual(always.call_count, 3)


class ExporterRowTests(unittest.TestCase):
    def test_ready_row_has_trace_tokens_cost_and_gt_pass(self):
        result = build([root_trace()], child_spans())
        row = result.rows[0]
        self.assertEqual(row["comparison_ready"], 1, row["comparison_warning"])
        self.assertEqual((row["token_source"], row["trace_total_tokens"], row["trace_cost_usd"]), ("trace", 1800, 0.0002))
        self.assertEqual((row["ground_truth_adherence_pass"], row["quality_ready"], row["cost_ready"]), (1, 1, 1))
        self.assertEqual(row["scenario_id"], "Q01")
        self.assertEqual(row["observed_llm_models"], "gpt-5-nano-2025-08-07")
        self.assertEqual(row["trace_cost_status"], "success")
        self.assertEqual(row["judge_model"], "gpt-4.1-mini")
        self.assertEqual(row["judge_cost_usd"], 0.001)
        self.assertEqual(row["context_adherence_score"], 0.9)
        self.assertEqual(row["ground_truth_adherence_rationale"], "matches\\nfacts")
        self.assertEqual((row["tool_call_count"], row["retriever_call_count"]), (1, 1))
        self.assertEqual(row["trace_duration_seconds"], 4.0)
        self.assertEqual(result.warnings[-1][:12], "Experiment '")  # nine planned questions missing

    def test_context_adherence_uses_final_answer_llm_span(self):
        trace = root_trace()
        trace["metric_info"]["ca-1"] = {"metric_key_alias": "groundedness", "status_type": "roll_up", "value": None}
        spans = child_spans()
        decision, final = dict(spans[0]), dict(spans[0])
        decision.update(id="T1-llm-1", created_at="2026-10-21T07:11:01Z", metric_info={
            "ca": {"metric_key_alias": "groundedness", "status_type": "success", "value": 0.0, "cost": 0.03}})
        final.update(id="T1-llm-2", created_at="2026-10-21T07:11:09.5+00:00", metric_info={
            "ca": {"metric_key_alias": "groundedness", "status_type": "success", "value": 1.0, "cost": 0.02}})
        row = build([trace], [final, decision, *spans[1:]]).rows[0]
        self.assertEqual((row["context_adherence_score"], row["context_adherence_status"]), (1.0, "success"))
        self.assertAlmostEqual(row["context_adherence_cost_usd"], 0.05)
        self.assertNotIn("context_adherence", row["comparison_warning"])
        final["metric_info"] = {"ca": {"metric_key_alias": "groundedness", "status_type": "pending", "value": None}}
        row = build([trace], [decision, final, *spans[1:]]).rows[0]
        self.assertEqual((row["context_adherence_score"], row["context_adherence_status"]), (None, "pending"))
        self.assertIn("context_adherence_pending", row["comparison_warning"])

    def test_zero_or_missing_platform_cost_is_not_comparison_ready(self):
        zero = build([root_trace(cost=0.0)], child_spans()).rows[0]
        self.assertEqual((zero["cost_ready"], zero["comparison_ready"]), (0, 0))
        self.assertIn("platform_cost_zero_with_tokens", zero["comparison_warning"])
        missing = build([root_trace(cost=None)], child_spans()).rows[0]
        self.assertEqual((missing["trace_cost_usd"], missing["comparison_ready"]), (None, 0))
        self.assertIn("trace_cost_missing", missing["comparison_warning"])

    def test_tokens_fall_back_to_llm_spans(self):
        row = build([root_trace(tokens=None)], child_spans(tokens=(100, 20, 120))).rows[0]
        self.assertEqual((row["token_source"], row["trace_input_tokens"], row["trace_total_tokens"]), ("llm_spans", 100, 120))
        none = build([root_trace(tokens=None)], [s for s in child_spans() if s["type"] != "llm"]).rows[0]
        self.assertEqual((none["token_source"], none["trace_total_tokens"], none["cost_ready"]), ("", None, 0))
        self.assertIn("no_llm_model_observed", none["comparison_warning"])

    def test_status_code_zero_ok_http_error_not_ready(self):
        self.assertEqual(build([root_trace(status_code=200)], child_spans()).rows[0]["comparison_ready"], 1)
        failed = build([root_trace(status_code=500)], child_spans()).rows[0]
        self.assertEqual(failed["comparison_ready"], 0)
        self.assertIn("trace_status_500", failed["comparison_warning"])

    def test_pending_judge_and_failing_score(self):
        pending = build([root_trace(gt="pending")], child_spans()).rows[0]
        self.assertEqual((pending["ground_truth_adherence_scored"], pending["ground_truth_adherence_pass"],
                          pending["quality_ready"], pending["comparison_ready"]), (0, "", 0, 0))
        self.assertIn("ground_truth_adherence_pending", pending["comparison_warning"])
        failing = build([root_trace(gt_value=0.25)], child_spans()).rows[0]
        self.assertEqual((failing["ground_truth_adherence_pass"], failing["comparison_ready"]), (0, 1))

    def test_dataset_version_model_and_tag_mismatches(self):
        version = build([root_trace()], child_spans(), tags={**TAGS, "dataset_version": "old"})
        self.assertIn("dataset_not_in_plan", version.rows[0]["comparison_warning"])
        self.assertEqual(version.rows[0]["comparison_ready"], 0)
        other = build([root_trace()], child_spans(model="gpt-4o"))
        self.assertIn("application_model_mismatch", other.rows[0]["comparison_warning"])
        untagged = build([root_trace()], child_spans(), tags={k: v for k, v in TAGS.items() if k != "api_mode"})
        self.assertIn("missing_runtime_tags", untagged.rows[0]["comparison_warning"])
        self.assertTrue(any("api_mode" in w for w in untagged.warnings))
        chaos = build([root_trace()], child_spans(), tags={**TAGS, "chaos_state": "rag"})
        self.assertIn("chaos_not_off", chaos.rows[0]["comparison_warning"])

    def test_duplicate_traces_and_scenarios(self):
        result = build([root_trace("T1"), root_trace("T1"), root_trace("T2")],
                       child_spans("T1") + child_spans("T2"))
        self.assertEqual([r["trace_id"] for r in result.rows], ["T1", "T2"])
        self.assertTrue(any("T1" in w for w in result.warnings))
        for row in result.rows:
            self.assertIn("duplicate_scenario_in_experiment", row["comparison_warning"])
            self.assertEqual(row["comparison_ready"], 0)

    def test_agent_error_and_control_intervention(self):
        error = build([root_trace(output="Error processing your request: boom")], child_spans()).rows[0]
        self.assertEqual((error["agent_error"], error["comparison_ready"]), (1, 0))


class ExporterWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "out.csv")

    def rows(self):
        traces, spans = [], []
        for index in range(len(QUESTIONS)):
            traces.append(root_trace(f"A{index}", index, cost=0.0001 * (index + 1), gt_value=1.0 if index % 2 else 0.0))
            spans += child_spans(f"A{index}")
        nano = build(traces, spans).rows
        sol_tags = {**TAGS, "application_model": "gpt-6.1-sol"}
        traces = [root_trace(f"B{i}", i, cost=0.002) for i in range(len(QUESTIONS))]
        spans = [s for i in range(len(QUESTIONS)) for s in child_spans(f"B{i}", model="gpt-6.1-sol")]
        sol = build(traces, spans, tags=sol_tags, exp=experiment("E2", "Cisco SE Model Economics - gpt-6.1-sol - R1")).rows
        return nano + sol

    def test_atomic_write_round_trip_and_summary(self):
        rows = econ.write_csv_atomic(self.rows(), self.path)
        self.assertEqual(len(rows), 20)
        with open(self.path, newline="", encoding="utf-8") as handle:
            text = handle.read()
            handle.seek(0)
            reread = list(csv.DictReader(handle))
        self.assertEqual(len(text.splitlines()), 21)
        self.assertEqual(len({(r["experiment_id"], r["trace_id"]) for r in reread}), 20)
        self.assertEqual(list(reread[0]), econ.FIELDS)
        summary = {s["application_model"]: s for s in econ.summarize(reread)}
        nano, sol = summary["gpt-5-nano"], summary["gpt-6.1-sol"]
        self.assertEqual((nano["rows"], nano["comparison_ready_rows"], nano["gt_scored"], nano["gt_passed"]), (10, 10, 10, 5))
        self.assertAlmostEqual(nano["gt_pass_rate"], 0.5)
        self.assertAlmostEqual(nano["app_cost_usd"], 0.0055)
        self.assertAlmostEqual(nano["cost_per_passing_answer_usd"], 0.0055 / 5)
        self.assertAlmostEqual(sol["app_cost_usd"], 0.02)
        self.assertEqual(sol["gt_pass_rate"], 1.0)
        self.assertEqual(sol["total_tokens"], 18000)
        self.assertEqual(sol["p95_latency_s"], 4.0)
        self.assertEqual(econ.pairing_warnings(reread), [])
        self.assertIn("gpt-6.1-sol", econ.format_summary(econ.summarize(reread)))

    def test_failed_write_keeps_previous_csv(self):
        econ.write_csv_atomic(self.rows(), self.path)
        before = Path(self.path).read_bytes()
        bad = self.rows()
        bad[1]["trace_id"] = bad[0]["trace_id"]
        with self.assertRaises(econ.ExportError):
            econ.write_csv_atomic(bad, self.path)
        ready_without_cost = self.rows()
        ready_without_cost[0]["trace_cost_usd"] = None
        with self.assertRaises(econ.ExportError):
            econ.write_csv_atomic(ready_without_cost, self.path)
        self.assertEqual(Path(self.path).read_bytes(), before)
        self.assertEqual([p for p in os.listdir(self.tmp.name) if p.endswith(".tmp")], [])

    def test_p95_nearest_rank_and_pairing_mismatch(self):
        self.assertIsNone(econ.p95([]))
        self.assertEqual(econ.p95([float(i) for i in range(1, 21)]), 19.0)
        self.assertEqual(econ.p95([3.0]), 3.0)
        rows = econ.write_csv_atomic(self.rows(), self.path)
        for row in rows:
            if row["application_model"] == "gpt-6.1-sol":
                row["dataset_hash"] = "other"
        self.assertTrue(any("dataset_hash" in w for w in econ.pairing_warnings(rows)))


if __name__ == "__main__":
    unittest.main()
