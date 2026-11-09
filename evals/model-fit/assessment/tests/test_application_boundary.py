"""Application use cases load and execute without native or filesystem adapters."""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class ApplicationBoundaryTests(unittest.TestCase):
    def test_assessment_runs_with_ports_without_loading_external_adapters(self):
        program = '\nimport sys\nfrom model_fit.assessment.assess import assess\nfrom model_fit.assessment.validation import empty_decision\nprofile = {"model":"fixture", "effort":"low", "speed":None}\nrequest = {"task":"bounded work", "active_profile":profile}\nclass FixtureCatalog:\n    def supported(self, profile):\n        return True\nmodels = FixtureCatalog()\nresult = assess(request, "fixture", "low", 1, source_reader=lambda:("source",models), evaluator=lambda *args:empty_decision(profile,"keep","suitable"))\nassert result["decision"] == "keep"\nassert not any(name.startswith(("model_fit.infrastructure", "model_fit.entrypoints")) for name in sys.modules)\n'
        result = subprocess.run(
            [sys.executable, "-I", "-c", program],
            capture_output=True,
            text=True,
            timeout=60,
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

    def test_deferred_assessment_preserves_opaque_native_content(self):
        from unittest.mock import MagicMock
        from model_fit.entrypoints.hooks import operations as api

        content = [
            {"type": "text", "text": "bounded work", "text_elements": []},
            {
                "type": "image",
                "url": "fixture-image",
                "future_metadata": {"opaque": ["retained", 7]},
            },
        ]
        profile = {"model": "fixture", "effort": "low", "speed": None}
        event = {
            "session_id": "opaque-thread",
            "turn_id": "turn",
            "prompt": "bounded work",
            "cwd": "/fixture",
            "model": "fixture",
        }
        reader = MagicMock()

        def rpc(method, params, timeout):
            if method == "thread/read":
                return {"thread": {"model": "fixture", "reasoningEffort": "low"}}
            if method == "thread/items/list":
                return {
                    "data": [
                        {
                            "item": {
                                "id": "native-message",
                                "clientId": "composer",
                                "type": "userMessage",
                                "content": content,
                            }
                        }
                    ],
                    "nextCursor": None,
                }
            raise AssertionError(method)

        reader.__enter__.return_value.call.side_effect = rpc
        observed = []
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {"CODEX_HOME": directory, "CODEX_THREAD_ID": "opaque-thread"},
            ),
        ):
            with patch.object(
                api, "session_input", side_effect=AssertionError("Early native read")
            ):
                api.submit_prompt(event)
            api.assess_submitted(
                context_reader=lambda _: {
                    "task": "bounded work",
                    "active_profile": profile,
                },
                assessor=lambda request: (
                    observed.append(request["input"]) or {"decision": "keep"}
                ),
                native_factory=lambda _: reader,
            )
        self.assertEqual(observed, [content])
