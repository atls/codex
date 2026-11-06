"""Check the thin provider's no-model controls and error result."""

import json
import unittest
from unittest.mock import patch

from controller.provider import call_api, TRIAGE


class ControllerProviderTests(unittest.TestCase):
    def test_selected_executable_reaches_production_run(self):
        selected = "/fixture/bundled-codex"
        with patch.object(TRIAGE, "assess", return_value={"decision": "keep"}) as run:
            result = call_api(
                json.dumps({"case_id": "bounded-read-only-list"}),
                {"config": {"codex_path": selected}},
                {},
            )
        self.assertNotIn("error", result)
        self.assertEqual(run.call_args.kwargs["codex_path"], selected)

    def test_corpus_request_uses_live_sources_and_original_context(self):
        request = {
            "task": "original request",
            "context": "recorded context",
            "active_profile": {
                "model": "gpt-6.1-sol",
                "effort": "medium",
                "speed": None,
            },
        }
        with patch.object(TRIAGE, "assess", return_value={"decision": "keep"}) as run:
            result = call_api(json.dumps({"request": request}), {}, {})
        self.assertEqual(run.call_args.args[0], request)
        self.assertIsNone(run.call_args.args[4])
        self.assertEqual(result["metadata"]["source_mode"], "live-official-sources")

    def test_prior_choice_uses_the_production_bypass_without_inference(self):
        with patch.object(
            TRIAGE, "AppServer", side_effect=AssertionError("Inference started")
        ):
            result = call_api(json.dumps({"case_id": "user-choice-preserved"}), {}, {})
        self.assertEqual(json.loads(result["output"])["decision"], "keep")
        self.assertTrue(result["metadata"]["user_choice_bypass"])
        self.assertEqual(result["metadata"]["model_turns"], 0)

    def test_source_failure_is_explicitly_a_simulation_without_inference(self):
        with patch.object(
            TRIAGE, "AppServer", side_effect=AssertionError("Inference started")
        ):
            result = call_api(json.dumps({"case_id": "catalog-unavailable"}), {}, {})
        self.assertEqual(json.loads(result["output"])["decision"], "unknown")
        self.assertTrue(result["metadata"]["source_failure_simulation"])
        self.assertEqual(result["metadata"]["model_turns"], 0)

    def test_bad_input_is_provider_error_not_success(self):
        result = call_api("not JSON", {}, {})
        self.assertIn("error", result)
        self.assertNotIn("output", result)


if __name__ == "__main__":
    unittest.main()


class ControllerRawEvidenceTests(unittest.TestCase):
    def test_early_failure_retains_available_raw_events_error_and_cumulative_ledger(
        self,
    ):
        total = {
            "totalTokens": 1000,
            "inputTokens": 900,
            "outputTokens": 100,
            "cachedInputTokens": 700,
            "reasoningOutputTokens": 20,
        }
        events = [
            {
                "method": "thread/tokenUsage/updated",
                "params": {"tokenUsage": {"total": total, "last": {"totalTokens": 2}}},
            }
        ]

        def fail(request, model, effort, timeout, bundle, diagnostics, **kwargs):
            diagnostics.update(
                {
                    "events": events,
                    "usage": {"total": total, "last": {"totalTokens": 2}},
                }
            )
            raise TimeoutError("fixture partial turn")

        with patch.object(TRIAGE, "assess", side_effect=fail):
            result = call_api(json.dumps({"case_id": "bounded-read-only-list"}), {}, {})
        self.assertEqual(result["error"], "TimeoutError")
        self.assertEqual(result["tokenUsage"]["total"], 1000)
        raw = json.loads(result["raw"])
        self.assertEqual(raw["events"], events)
        self.assertEqual(raw["usage"]["total"], total)
        self.assertEqual(raw["error"]["message"], "fixture partial turn")

    def test_unknown_usage_is_not_an_invented_zero_and_controls_are_not_applicable(
        self,
    ):
        with patch.object(TRIAGE, "assess", side_effect=TimeoutError("no events")):
            failed = call_api(json.dumps({"case_id": "bounded-read-only-list"}), {}, {})
        self.assertNotIn("tokenUsage", failed)
        self.assertEqual(failed["metadata"]["usage_status"], "unknown")
        control = call_api(json.dumps({"case_id": "catalog-unavailable"}), {}, {})
        self.assertNotIn("tokenUsage", control)
        self.assertEqual(control["metadata"]["usage_status"], "not-applicable")
        self.assertEqual(control["metadata"]["model_turns"], 0)
