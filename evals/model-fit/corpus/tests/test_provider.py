import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE))
from corpus.evidence import cumulative_usage
from corpus.snapshot import snapshot_hash

SPEC = importlib.util.spec_from_file_location(
    "corpus_provider", SUITE / "corpus/provider.py"
)
PROVIDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROVIDER)

ACTIVE = {"model": "gpt-6.1-sol", "effort": "medium", "speed": None}
CONFIG = {
    "mode": "model-fit",
    "execution": {
        "codex_path_override": "/fixture/codex",
        "cli_env": {"CODEX_HOME": "/fixture/isolated-home"},
    },
}
CONTEXT = {"vars": {"active_profile": ACTIVE, "task_context": "original context"}}
LEDGER = {
    "totalTokens": 1000,
    "inputTokens": 900,
    "outputTokens": 100,
    "cachedInputTokens": 600,
    "reasoningOutputTokens": 30,
}
PREFLIGHT = {
    "output": json.dumps({"decision": "keep"}),
    "metadata": {"skill_item_seen": True, "model_turns": 1},
    "raw": json.dumps({"usage": {"total": LEDGER, "last": {"totalTokens": 4}}}),
}
EXECUTOR = {
    "output": "answer",
    "tokenUsage": {"total": 5},
    "raw": json.dumps(
        {
            "tokenUsage": {
                "total": {**LEDGER, "totalTokens": 2000, "inputTokens": 1900},
                "last": {"totalTokens": 5},
            },
            "notifications": [
                {
                    "method": "thread/settings/updated",
                    "params": {
                        "threadSettings": {
                            **{k: ACTIVE[k] for k in ["model", "effort"]},
                            "serviceTier": None,
                        }
                    },
                }
            ],
        }
    ),
}


class CorpusProviderTests(unittest.TestCase):
    def test_full_stage_ledgers_and_raw_survive_without_cross_model_sum(self):
        with patch.object(PROVIDER, "controller_call", return_value=PREFLIGHT):
            response = PROVIDER.prepare("task", {"config": CONFIG}, CONTEXT)
        plan = json.loads(response["output"])
        result = PROVIDER.finalize(
            json.dumps({"prepared": plan, "execution": EXECUTOR}), {}, CONTEXT
        )
        self.assertEqual(result["output"], "answer")
        self.assertEqual(result["raw"], EXECUTOR["raw"])
        self.assertEqual(result["tokenUsage"]["total"], 2000)
        stages = result["metadata"]["corpusStages"]
        self.assertEqual(stages["preflight"]["cumulativeUsage"]["totalTokens"], 1000)
        self.assertEqual(stages["preflight"]["response"]["raw"], PREFLIGHT["raw"])
        self.assertEqual(stages["execution"]["profileEvidenceStatus"], "matched")
        self.assertEqual(
            plan["provider"]["options"]["config"]["model"], ACTIVE["model"]
        )

    def test_preflight_failure_preserves_partial_usage_and_no_executor_plan(self):
        partial = {**PREFLIGHT, "error": "fixture timeout"}
        with patch.object(PROVIDER, "controller_call", return_value=partial):
            result = PROVIDER.prepare("task", {"config": CONFIG}, CONTEXT)
        self.assertEqual(result["error"], "fixture timeout")
        self.assertEqual(
            result["metadata"]["corpusStages"]["preflight"]["response"]["raw"],
            partial["raw"],
        )
        self.assertEqual(
            result["metadata"]["corpusStages"]["execution"]["usageStatus"],
            "not-applicable",
        )
        self.assertNotIn("tokenUsage", result)

    def test_stock_does_not_call_preflight_or_invent_last_as_total(self):
        with patch.object(
            PROVIDER, "controller_call", side_effect=AssertionError("No preflight")
        ):
            plan = json.loads(
                PROVIDER.prepare(
                    "task", {"config": {**CONFIG, "mode": "stock-control"}}, CONTEXT
                )["output"]
            )
        result = PROVIDER.finalize(
            json.dumps(
                {
                    "prepared": plan,
                    "execution": {
                        "output": "answer",
                        "raw": json.dumps({"tokenUsage": {"last": {"totalTokens": 5}}}),
                    },
                }
            ),
            {},
            CONTEXT,
        )
        self.assertEqual(
            result["metadata"]["corpusStages"]["preflight"]["usageStatus"],
            "not-applicable",
        )
        self.assertEqual(
            result["metadata"]["corpusStages"]["execution"]["usageStatus"], "unknown"
        )
        self.assertNotIn("tokenUsage", result)

    def test_missing_authenticated_home_stops_before_preflight(self):
        with patch.object(
            PROVIDER, "controller_call", side_effect=AssertionError("Wrong login")
        ):
            result = PROVIDER.prepare(
                "task", {"config": {"mode": "model-fit", "execution": {}}}, CONTEXT
            )
        self.assertIn("isolated controller CODEX_HOME", result["error"])

    def test_snapshot_mutation_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            for root in [source, workspace]:
                (root / "facts").write_text("facts")
            expected = snapshot_hash(source)
            context = {
                "vars": {
                    **CONTEXT["vars"],
                    "workspace": str(workspace),
                    "snapshot_directory": str(source),
                    "snapshot_hash": expected,
                }
            }
            plan = json.loads(
                PROVIDER.prepare(
                    "task", {"config": {**CONFIG, "mode": "stock-control"}}, context
                )["output"]
            )
            (workspace / "facts").write_text("changed")
            result = PROVIDER.finalize(
                json.dumps({"prepared": plan, "execution": EXECUTOR}), {}, context
            )
            self.assertIn("Snapshot changed", result["error"])
            self.assertEqual(result["metadata"]["snapshot"]["sourceAfter"], expected)

    def test_profile_mismatch_is_not_success(self):
        plan = json.loads(
            PROVIDER.prepare(
                "task", {"config": {**CONFIG, "mode": "stock-control"}}, CONTEXT
            )["output"]
        )
        wrong = {**EXECUTOR, "raw": EXECUTOR["raw"].replace("gpt-6.1-sol", "other")}
        result = PROVIDER.finalize(
            json.dumps({"prepared": plan, "execution": wrong}), {}, CONTEXT
        )
        self.assertIn("profile differs", result["error"])

    def test_ledger_fallback_and_malformed_raw_remain_unknown(self):
        self.assertEqual(
            cumulative_usage(
                {"raw": {"tokenUsage": {"last": {}}, "usage": {"total": LEDGER}}}
            ),
            LEDGER,
        )
        self.assertIsNone(cumulative_usage({"raw": "[]"}))

    def test_selected_profile_is_forwarded_to_the_native_executor(self):
        response = {
            **PREFLIGHT,
            "output": json.dumps(
                {
                    "decision": "recommend_lighter",
                    "recommended_model": "gpt-6-luna",
                    "recommended_effort": "low",
                }
            ),
        }
        with patch.object(PROVIDER, "controller_call", return_value=response):
            plan = json.loads(
                PROVIDER.prepare("task", {"config": CONFIG}, CONTEXT)["output"]
            )
        self.assertEqual(plan["provider"]["options"]["config"]["model"], "gpt-6-luna")
        self.assertEqual(
            plan["provider"]["options"]["config"]["model_reasoning_effort"], "low"
        )
        self.assertEqual(plan["active"], ACTIVE)

    def test_unknown_preflight_never_produces_an_executor_plan(self):
        response = {**PREFLIGHT, "output": json.dumps({"decision": "unknown"})}
        with patch.object(PROVIDER, "controller_call", return_value=response):
            result = PROVIDER.prepare("task", {"config": CONFIG}, CONTEXT)
        self.assertEqual(result["error"], "Model Fit returned unknown")
        self.assertEqual(
            result["metadata"]["corpusStages"]["execution"]["status"], "not-invoked"
        )

    def test_snapshot_symlinks_are_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real").write_text("data")
            (root / "link").symlink_to(root / "real")
            with self.assertRaisesRegex(ValueError, "symlink"):
                snapshot_hash(root)
