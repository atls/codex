import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assessment import scenarios

from assessment.scenarios import fixtures, loading


class NativeGeneratorTests(unittest.TestCase):
    def generate(self, surface, root, **kwargs):
        return scenarios.generate_tests(
            {
                "surface": surface,
                "workspace_root": root,
                "skill_file": "/fixture/SKILL.md",
                "judge": {
                    "id": "openai:codex-app-server",
                    "config": {"model": "fixture"},
                },
                **kwargs,
            }
        )

    def test_native_assessment_and_ordinary_preserve_ids_context_and_provider_refs(
        self,
    ):
        cases = scenarios.load_scenarios()
        with tempfile.TemporaryDirectory() as root:
            for surface in ["native", "assessment", "ordinary"]:
                rows = self.generate(surface, root)
                selected = [
                    case
                    for case in cases
                    if (
                        bool(case.get("implicit_selection_control"))
                        if surface == "ordinary"
                        else not case.get("implicit_selection_control")
                    )
                    and (
                        surface != "native"
                        or not case.get("source_failure")
                        and not case.get("prior_choice")
                    )
                ]
                self.assertEqual(
                    [row["description"] for row in rows],
                    [case["id"] for case in selected],
                )
                for row, case in zip(rows, selected):
                    self.assertEqual(
                        row["vars"]["task_context"],
                        scenarios.fixture_context(case) or "",
                    )
                    self.assertTrue(Path(row["vars"]["workspace"], ".git").is_dir())
                    for assertion in row["assert"]:
                        if "llm-rubric" in assertion["type"]:
                            self.assertEqual(
                                assertion["provider"]["id"], "openai:codex-app-server"
                            )
                    if case.get("fixture_directory"):
                        source = fixtures.SUITE / case["fixture_directory"]
                        for file in source.rglob("*"):
                            if file.is_file():
                                self.assertEqual(
                                    (
                                        Path(row["vars"]["workspace"])
                                        / case.get("fixture_target", "")
                                        / file.relative_to(source)
                                    ).read_bytes(),
                                    file.read_bytes(),
                                )

    def test_calibration_labels_are_not_leaked_to_judge(self):
        with tempfile.TemporaryDirectory() as root:
            rows = self.generate("calibration", root)
            self.assertEqual(len(rows), 25)
            self.assertEqual(len({row["description"] for row in rows}), 25)
            self.assertEqual(rows[-3]["description"], "fabricated-official-policy")
            self.assertEqual(rows[-2]["assert"][0]["type"], "llm-rubric")
            self.assertEqual(rows[-1]["assert"][0]["type"], "not-llm-rubric")
            self.assertTrue(all("expected_pass" not in row["vars"] for row in rows))
            self.assertIn(
                "resolving ownership conflicts",
                json.loads(rows[-2]["vars"]["answer"])["task_inference"],
            )

    def test_regrade_preserves_retained_answers_and_excludes_no_model_controls(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "saved.json"
            source.write_text(
                json.dumps(
                    {
                        "results": {
                            "results": [
                                {
                                    "testCase": {
                                        "description": "bounded-read-only-list"
                                    },
                                    "response": {"output": "retained exact answer"},
                                },
                                {
                                    "testCase": {"description": "catalog-unavailable"},
                                    "response": {"output": "excluded"},
                                },
                            ]
                        }
                    }
                )
            )
            rows = self.generate("regrade", root, saved_result=str(source))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["vars"]["answer"], "retained exact answer")

    def test_behavioral_requirements_reach_judge_without_model_whitelist(self):
        identifiers = {
            "thread-memory-client-discovery",
            "thread-memory-read-completion",
            "bounded-checkin-after-runtime-failure",
            "failed-profile-work-still-unfinished",
        }
        with tempfile.TemporaryDirectory() as root:
            rows = self.generate("native", root)
            selected = [row for row in rows if row["description"] in identifiers]
            self.assertEqual({row["description"] for row in selected}, identifiers)
            for row in selected:
                case = row["vars"]["scenario"]
                self.assertFalse(case["allowed_recommendations"])
                rubric = next(
                    a["value"] for a in row["assert"] if a["type"] == "llm-rubric"
                )
                self.assertIn(case["quality_requirements"], rubric)

    def test_missing_runtime_invalid_surface_and_workspace_escape_fail(self):
        with self.assertRaises(ValueError):
            scenarios.generate_tests()
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                self.generate("wrong", root)
            for identifier in ["../escape", "/outside", ".", ""]:
                with self.assertRaises(ValueError):
                    scenarios.prepare_workspace(root, identifier)
            (Path(root) / "link").symlink_to(Path(root) / "missing")
            with self.assertRaises(ValueError):
                scenarios.prepare_workspace(root, "link")

    def test_duplicate_ids_and_unknown_base_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            (home / "fixtures").mkdir()
            original = {"id": "base", "prompt": "fixture"}
            spec = {"id": "case", "base_case_id": "base"}
            with patch.object(loading, "SUITE", home):
                (home / "fixtures/cases.json").write_text(
                    json.dumps([original, original])
                )
                (home / "fixtures/triage-cases.json").write_text(json.dumps([spec]))
                with self.assertRaises(ValueError):
                    scenarios.load_scenarios()
                (home / "fixtures/cases.json").write_text(json.dumps([original]))
                (home / "fixtures/triage-cases.json").write_text(
                    json.dumps([spec, spec])
                )
                with self.assertRaises(ValueError):
                    scenarios.load_scenarios()
                (home / "fixtures/triage-cases.json").write_text(
                    json.dumps([spec | {"base_case_id": "missing"}])
                )
                with self.assertRaises(ValueError):
                    scenarios.load_scenarios()

    def test_parent_symlink_and_oversized_fixture_context_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            (home / "real/sub").mkdir(parents=True)
            (home / "real/sub/large.md").write_text("x" * 20001)
            (home / "link").symlink_to(home / "real")
            with patch.object(fixtures, "SUITE", home):
                for relative in ["link/sub", "real/sub"]:
                    with self.assertRaises(ValueError):
                        scenarios.fixture_context({"fixture_directory": relative})
