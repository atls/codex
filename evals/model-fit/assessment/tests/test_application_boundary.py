"""Application use cases load and execute without native or filesystem adapters."""

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ApplicationBoundaryTests(unittest.TestCase):
    def test_scenarios_do_not_import_the_removed_layers_or_facade(self):
        source = Path(__file__).resolve().parents[4] / "plugins/model-fit/src"
        forbidden = (
            "model_fit.application",
            "model_fit.api",
            "model_fit.infrastructure.handoff",
            "model_fit.infrastructure.assessment",
        )
        checked = []
        for folder in ("assessment", "submission", "autoswitch", "answer"):
            for path in (source / folder).rglob("*.py"):
                checked.append(path)
                for node in ast.walk(ast.parse(path.read_text())):
                    names = (
                        [node.module]
                        if isinstance(node, ast.ImportFrom)
                        else [item.name for item in node.names]
                        if isinstance(node, ast.Import)
                        else []
                    )
                    self.assertFalse(
                        any((name and name.startswith(forbidden) for name in names)),
                        str(path),
                    )
        self.assertTrue(checked)

    def test_assessment_runs_with_ports_without_loading_external_adapters(self):
        program = '\nimport sys\nfrom model_fit.assessment.assess import assess\nfrom model_fit.assessment.validation import empty_decision\nprofile = {"model":"fixture", "effort":"low", "speed":None}\nrequest = {"task":"bounded work", "active_profile":profile}\nclass FixtureCatalog:\n    def supported(self, profile):\n        return True\nmodels = FixtureCatalog()\nresult = assess(request, "fixture", "low", 1, source_reader=lambda:("source",models), evaluator=lambda *args:empty_decision(profile,"keep","suitable"))\nassert result["decision"] == "keep"\nassert not any(name.startswith(("model_fit.infrastructure", "model_fit.entrypoints")) for name in sys.modules)\n'
        result = subprocess.run(
            [sys.executable, "-I", "-c", program], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tool_admission_does_not_require_queue_working_directory(self):
        from model_fit.entrypoints.hooks.operations import guard_tool

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"CODEX_HOME": directory}),
        ):
            with patch(
                "model_fit.entrypoints.hooks.operations.os.getcwd",
                side_effect=FileNotFoundError("retired cwd"),
            ) as cwd:
                self.assertIsNone(
                    guard_tool({"session_id": "thread", "turn_id": "turn"})
                )
            cwd.assert_not_called()

    def test_context_reader_receives_the_original_opaque_native_event(self):
        from model_fit.entrypoints.hooks.operations import prepare_handoff

        marker = object()
        event = {
            "session_id": "opaque-thread",
            "turn_id": "turn",
            "prompt": "bounded work",
            "model": "fixture",
            "future_native_field": marker,
        }
        profile = {"model": "fixture", "effort": "low", "speed": None}

        def read_context(received):
            self.assertIs(received, event)
            self.assertIs(received["future_native_field"], marker)
            return {"task": event["prompt"], "active_profile": profile}

        def no_native_process(_):
            self.fail("A keep decision must not open the queue reader")

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"CODEX_HOME": directory}),
        ):
            self.assertIsNone(
                prepare_handoff(
                    event,
                    context_reader=read_context,
                    assessor=lambda request: {"decision": "keep"},
                    native_factory=no_native_process,
                )
            )

    def test_application_does_not_unpack_the_opaque_native_source(self):
        source = Path(__file__).resolve().parents[4] / "plugins/model-fit" / "src"
        for path in (
            path
            for folder in ("assessment", "submission", "autoswitch", "answer")
            for path in (source / folder).rglob("*.py")
        ):
            for node in ast.walk(ast.parse(path.read_text())):
                with self.subTest(module=str(path.relative_to(source))):
                    self.assertFalse(
                        isinstance(node, ast.Attribute) and node.attr == "source"
                    )
