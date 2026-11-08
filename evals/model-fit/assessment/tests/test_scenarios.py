"""Validate reusable scenario data without running an evaluator."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assessment import scenarios

from assessment.scenarios import fixtures


class ScenarioDataTests(unittest.TestCase):
    def test_original_task_and_fixture_context_are_preserved(self):
        case = scenarios.load_scenarios(["writer-preflight"])[0]
        self.assertEqual(case["task_prompt"], case["prompt"])
        self.assertIn("TASK.md", scenarios.fixture_context(case))

    def test_unknown_case_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown scenarios"):
            scenarios.load_scenarios(["not-a-case"])

    def test_fixtures_cannot_escape_or_follow_symlinks(self):
        for value in ("../private", "/private"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                scenarios.fixture_context({"fixture_directory": value})
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "real").mkdir()
            (root / "link").symlink_to(root / "real", target_is_directory=True)
            with patch.object(fixtures, "SUITE", root), self.assertRaises(ValueError):
                scenarios.fixture_context({"fixture_directory": "link"})

    def test_calibration_ids_and_labels_match_scenarios(self):
        cases = {x["id"] for x in scenarios.load_scenarios()}
        controls = json.loads(
            (fixtures.SUITE / "fixtures/behavior-calibration.json").read_text()
        )
        self.assertEqual(len({x["id"] for x in controls}), len(controls))
        self.assertTrue(all(x["case_id"] in cases for x in controls))
        self.assertEqual({x["expected_pass"] for x in controls}, {True, False})

    def test_observed_behavior_cases_do_not_whitelist_a_profile(self):
        cases = [x for x in scenarios.load_scenarios() if x.get("behavioral_review")]
        self.assertEqual(len(cases), 14)
        for case in cases:
            self.assertFalse(case["allowed_recommendations"])

    def test_duplicate_catalog_models_are_rejected(self):
        source = '<codex_catalog>{"models":[{"slug":"same"},{"slug":"same"}]}</codex_catalog>'
        with self.assertRaises(ValueError):
            scenarios.catalog_models(source)
