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

    def test_surfaces_select_explicit_case_kinds_and_preserve_context(self):
        import copy
        from assessment.scenarios import generation

        original = scenarios.load_scenarios(["writer-preflight"])[0]
        normal = {
            **original,
            "id": "normal",
            "source_failure": None,
            "prior_choice": None,
            "implicit_selection_control": False,
        }
        cases = [
            normal,
            {**normal, "id": "source-error", "source_failure": "catalog"},
            {**normal, "id": "retained", "prior_choice": True},
            {**normal, "id": "dialogue", "implicit_selection_control": True},
        ]
        expected = {
            "native": ["normal"],
            "assessment": ["normal", "source-error", "retained"],
            "ordinary": ["dialogue"],
        }
        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(
                generation,
                "load_scenarios",
                side_effect=lambda selected: copy.deepcopy(cases),
            ),
        ):
            for surface, identifiers in expected.items():
                rows = self.generate(surface, root)
                self.assertEqual([row["description"] for row in rows], identifiers)
                for row in rows:
                    self.assertEqual(
                        row["vars"]["task_context"],
                        scenarios.fixture_context(normal) or "",
                    )
                    workspace = Path(row["vars"]["workspace"])
                    self.assertTrue((workspace / ".git").is_dir())
                    for assertion in row["assert"]:
                        if "llm-rubric" in assertion["type"]:
                            self.assertEqual(
                                assertion["provider"]["id"], "openai:codex-app-server"
                            )
                    for file in (fixtures.SUITE / normal["fixture_directory"]).rglob(
                        "*"
                    ):
                        if file.is_file():
                            self.assertEqual(
                                (
                                    workspace
                                    / normal.get("fixture_target", "")
                                    / file.relative_to(
                                        fixtures.SUITE / normal["fixture_directory"]
                                    )
                                ).read_bytes(),
                                file.read_bytes(),
                            )

    def test_calibration_labels_control_scoring_without_leaking_to_judge(self):
        from assessment.scenarios import generation

        controls = [
            {
                "id": "positive",
                "case_id": "bounded-read-only-list",
                "answer": {"reason": "valid answer"},
                "expected_pass": True,
            },
            {
                "id": "negative",
                "case_id": "bounded-read-only-list",
                "answer": {"reason": "invalid answer"},
                "expected_pass": False,
            },
        ]
        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(generation, "calibration_controls", return_value=controls),
        ):
            rows = {
                row["description"]: row for row in self.generate("calibration", root)
            }
        self.assertEqual(set(rows), {"positive", "negative"})
        self.assertEqual(rows["positive"]["assert"][0]["type"], "llm-rubric")
        self.assertEqual(rows["negative"]["assert"][0]["type"], "not-llm-rubric")
        for control in controls:
            row = rows[control["id"]]
            self.assertNotIn("expected_pass", row["vars"])
            self.assertEqual(json.loads(row["vars"]["answer"]), control["answer"])

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
                    (a["value"] for a in row["assert"] if a["type"] == "llm-rubric")
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
