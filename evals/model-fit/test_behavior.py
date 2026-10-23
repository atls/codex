"""Check that public calibration examples exercise the semantic grader boundary."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from model_fit_evals.files import load_scenarios
from model_fit_evals.grader import BEHAVIOR_CRITERIA, grade


HERE = Path(__file__).resolve().parent


class BehaviorGraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = next(
            case for case in load_scenarios(None) if case["id"] == "backlog-read"
        )
        self.answer = {
            "active_model": self.case["model"],
            "active_effort": self.case["effort"],
            "active_speed": self.case["speed"],
            "decision": "keep",
            "recommended_model": None,
            "recommended_effort": None,
            "recommended_speed": None,
            "official_source_url": None,
            "official_guidance": None,
            "task_inference": None,
            "reason": "The next action only lists three issues; this profile can do it.",
        }

    def result(self, checks: dict[str, bool]) -> dict:
        return {
            "status": "completed",
            "observed": {
                "messages": [json.dumps(self.answer)],
                "skill_item_seen": True,
                "tool_types": [],
                "task_tool_seen": False,
            },
            "behavioral_review": {
                "id": self.case["id"],
                "checks": checks,
                "explanation": "Grounded in the bounded request.",
            },
        }

    def test_all_semantic_criteria_are_required(self) -> None:
        checks = {key: True for key in BEHAVIOR_CRITERIA}
        self.assertTrue(grade(self.case, self.result(checks), {})["pass"])
        checks["grounded_change"] = False
        self.assertFalse(grade(self.case, self.result(checks), {})["pass"])

    def test_calibration_is_synthetic_and_has_positive_and_negative_cases(self) -> None:
        examples = json.loads((HERE / "behavior-calibration.json").read_text())
        scenario_ids = {case["id"] for case in load_scenarios(None)}
        self.assertEqual(len({row["id"] for row in examples}), len(examples))
        self.assertTrue({True, False} <= {row["expected_pass"] for row in examples})
        self.assertTrue(all(row["case_id"] in scenario_ids for row in examples))
        self.assertNotIn("codex://threads/", json.dumps(examples))


if __name__ == "__main__":
    unittest.main()
