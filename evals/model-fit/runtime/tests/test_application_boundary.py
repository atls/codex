"""Application use cases load and execute without native or filesystem adapters."""

import ast
import os
import tempfile
from unittest.mock import patch
import subprocess
import sys
import unittest
from pathlib import Path


class ApplicationBoundaryTests(unittest.TestCase):
    def test_application_dependencies_point_inward(self):
        source = (
            Path(__file__).resolve().parents[4] / "plugins/model-fit"
        ) / "src/application"
        forbidden = (
            "model_fit.infrastructure",
            "model_fit.entrypoints",
            "model_fit.api",
            "os",
            "pathlib",
            "subprocess",
            "fcntl",
            "tempfile",
            "shutil",
            "socket",
            "urllib.request",
        )
        for path in source.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names = (
                    [node.module]
                    if isinstance(node, ast.ImportFrom)
                    else [item.name for item in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                with self.subTest(module=str(path.relative_to(source))):
                    self.assertFalse(
                        any(name and name.startswith(forbidden) for name in names)
                    )

    def test_assessment_runs_with_ports_without_loading_external_adapters(self):
        program = """
import sys
from model_fit.application.assessment.assess import assess
from model_fit.application.assessment.validation import empty_decision
profile = {"model":"fixture", "effort":"low", "speed":None}
request = {"task":"bounded work", "active_profile":profile}
class FixtureCatalog:
    def supported(self, profile):
        return True
models = FixtureCatalog()
result = assess(request, "fixture", "low", 1, source_reader=lambda:("source",models), evaluator=lambda *args:empty_decision(profile,"keep","suitable"))
assert result["decision"] == "keep"
assert not any(name.startswith(("model_fit.infrastructure", "model_fit.entrypoints")) for name in sys.modules)
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", program], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tool_admission_does_not_require_queue_working_directory(self):
        from model_fit.api import guard_tool

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"CODEX_HOME": directory}),
        ):
            with patch(
                "model_fit.api.os.getcwd", side_effect=FileNotFoundError("retired cwd")
            ) as cwd:
                self.assertIsNone(
                    guard_tool({"session_id": "thread", "turn_id": "turn"})
                )
            cwd.assert_not_called()

    def test_context_reader_receives_the_original_opaque_native_event(self):
        from model_fit.api import prepare_handoff

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
        source = (
            Path(__file__).resolve().parents[4] / "plugins/model-fit"
        ) / "src/application"
        for path in source.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                with self.subTest(module=str(path.relative_to(source))):
                    self.assertFalse(
                        isinstance(node, ast.Attribute) and node.attr == "source"
                    )
