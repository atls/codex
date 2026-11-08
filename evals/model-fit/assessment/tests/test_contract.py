"""Boundary checks for the Promptfoo production-contract assertion."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assessment.decision_assertion import get_assert


class PromptfooContractTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2]
        cases = json.loads((root / "fixtures/triage-cases.json").read_text())
        self.case = next(
            case for case in cases if case["id"] == "bounded-read-only-list"
        )
        self.case["allowed_recommendations"] = self.case.get(
            "allowed_recommendations", []
        )
        source = (root / "fixtures/preflight-sources-2026-10-16.txt").read_text()
        catalog = json.loads(
            source.split("<codex_catalog>")[1].split("</codex_catalog>")[0]
        )["models"]
        self.context = {"vars": {"scenario": self.case, "catalog": catalog}}
        self.answer = {
            **{f"active_{key}": self.case[key] for key in ("model", "effort", "speed")},
            "decision": "keep",
            "recommended_model": None,
            "recommended_effort": None,
            "recommended_speed": None,
            "official_source_url": None,
            "official_guidance": None,
            "task_inference": None,
            "reason": "The active profile fits the bounded extraction.",
        }

    def test_actual_profile_must_match(self):
        self.assertTrue(get_assert(json.dumps(self.answer), self.context)["pass"])
        self.answer["active_model"] = "wrong"
        self.assertFalse(get_assert(json.dumps(self.answer), self.context)["pass"])

    def test_missing_or_malformed_answer_is_not_success(self):
        for answer in ("", "null", "{}", "[]"):
            with self.subTest(answer=answer):
                self.assertFalse(get_assert(answer, self.context)["pass"])

    def test_keep_cannot_contain_a_changed_profile(self):
        self.answer["recommended_model"] = "gpt-6-astra"
        self.assertFalse(get_assert(json.dumps(self.answer), self.context)["pass"])

    def test_valid_decision_can_fail_scenario_expectation(self):
        self.case["expected_decisions"] = ["recommend_stronger"]
        self.assertFalse(get_assert(json.dumps(self.answer), self.context)["pass"])

    def test_catalog_valid_target_can_fail_scenario_allowlist(self):
        target = next(
            row
            for row in self.context["vars"]["catalog"]
            if row["visibility"] == "list" and row["slug"] != self.case["model"]
        )
        level = target["supported_reasoning_levels"][0]
        effort = level["effort"] if isinstance(level, dict) else level
        self.case["expected_decisions"] = ["recommend_stronger"]
        self.case["allowed_recommendations"] = ["unrelated-target/low"]
        self.answer.update(
            decision="recommend_stronger",
            recommended_model=target["slug"],
            recommended_effort=effort,
            official_source_url="https://developers.openai.com/api/docs/guides/model-selection",
            official_guidance="Select a suitable profile.",
            task_inference="The next task requires deeper analysis.",
        )
        result = get_assert(json.dumps(self.answer), self.context)
        self.assertFalse(result["pass"])
        self.assertIn("Target differs", result["reason"])

    def test_assertion_loads_in_an_isolated_process_without_suite_pythonpath(self):
        assertion = Path(__file__).resolve().parents[1] / "decision_assertion.py"
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import runpy,sys; assert callable(runpy.run_path(sys.argv[1])['get_assert'])",
                    str(assertion),
                ],
                cwd=directory,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
