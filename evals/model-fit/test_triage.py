"""Deterministic checks for public Model Fit inputs and decisions."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "plugins/model-fit/skills/model-fit/scripts"
sys.path.insert(0, str(SCRIPTS))

from model_fit import preflight as PREFLIGHT
from model_fit_evals import context as EVAL_CONTEXT
from model_fit_evals.files import load_scenarios
from model_fit_evals.runner import run_case
from model_fit_evals.sources import catalog_supports_target


TRIAGE = EVAL_CONTEXT.TRIAGE


class PreflightContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.active = {"model": "gpt-6-luna", "effort": "low", "speed": "standard"}
        self.models = {
            slug: {
                "slug": slug,
                "visibility": "list",
                "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}],
                "additional_speed_tiers": [],
            }
            for slug in ("gpt-6-luna", "gpt-6.1-sol")
        }

    def recommendation(self) -> dict:
        return {
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "active_speed": "standard",
            "decision": "recommend_stronger",
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": None,
            "recommended_speed": None,
            "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
            "official_guidance": "Compare models on the same task.",
            "task_inference": "The requested design needs more reliable reasoning than the current profile provides.",
            "reason": "The next step is architecture design.",
        }

    def test_recommendation_preserves_active_profile_and_catalog_target(self) -> None:
        result = PREFLIGHT.validate(self.recommendation(), self.active, self.models)
        self.assertEqual(result["recommended_model"], "gpt-6.1-sol")
        self.assertIsNone(result["recommended_effort"])

    def test_off_catalog_target_is_rejected(self) -> None:
        output = self.recommendation()
        output["recommended_model"] = "unavailable-model"
        with self.assertRaisesRegex(ValueError, "catalog"):
            PREFLIGHT.validate(output, self.active, self.models)

    def test_unknown_speed_cannot_be_changed(self) -> None:
        active = dict(self.active, speed=None)
        output = self.recommendation()
        output["active_speed"] = None
        output["recommended_speed"] = "fast"
        with self.assertRaisesRegex(ValueError, "unknown speed"):
            PREFLIGHT.validate(output, active, self.models)

    def test_confirmed_user_choice_bypasses_sources_and_model(self) -> None:
        request = {
            "task": "Continue the same bounded task",
            "active_profile": self.active,
            "prior_choice": {
                "user_selected": True,
                "same_work": True,
                "profile": self.active,
            },
        }
        diagnostics = {}
        with patch.object(
            TRIAGE, "sources", side_effect=AssertionError("sources read")
        ):
            result = TRIAGE.run(
                request, "gpt-6.1-sol", "low", 1, diagnostics=diagnostics
            )
        self.assertEqual(result["decision"], "keep")
        self.assertEqual(diagnostics["agent_messages"], 0)
        self.assertTrue(diagnostics["user_choice_bypass"])

    def test_unavailable_source_returns_unknown_without_model_output(self) -> None:
        request = {"task": "Inspect one issue", "active_profile": self.active}
        visible = io.StringIO()
        with (
            patch.object(
                TRIAGE, "sources", side_effect=PREFLIGHT.SourceUnavailable("catalog")
            ),
            patch("sys.argv", ["triage.py"]),
            patch("sys.stdin", io.StringIO(json.dumps(request))),
            redirect_stdout(visible),
        ):
            code = TRIAGE.main()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(visible.getvalue())["decision"], "unknown")

    def test_public_scenarios_include_behavior_and_failure_controls(self) -> None:
        scenarios = load_scenarios(None)
        self.assertEqual(len(scenarios), 6)
        self.assertTrue(any(case["behavioral_review"] for case in scenarios))
        self.assertTrue(any(case.get("source_failure") for case in scenarios))
        self.assertEqual(len({case["id"] for case in scenarios}), len(scenarios))

    def test_catalog_accepts_unknown_speed_when_model_supports_effort(self) -> None:
        case = {"model": "gpt-6-luna", "effort": "low", "speed": None}
        output = {
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "medium",
            "recommended_speed": None,
        }
        self.assertTrue(catalog_supports_target(case, output, self.models))

    def test_source_failure_case_needs_no_model(self) -> None:
        case = next(
            case for case in load_scenarios(None) if case["id"] == "missing-source"
        )
        with tempfile.TemporaryDirectory() as directory:
            result = run_case(
                case,
                EVAL_CONTEXT.SKILL_DIR,
                Path(directory),
                {},
                "gpt-6-luna",
                "low",
                1,
                "",
            )
        self.assertEqual(
            json.loads(result["observed"]["messages"][0])["decision"], "unknown"
        )
        self.assertEqual(result["observed"]["tool_types"], [])


if __name__ == "__main__":
    unittest.main()
