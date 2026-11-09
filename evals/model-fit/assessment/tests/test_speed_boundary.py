import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import model_fit.entrypoints.cli.assess as cli
import model_fit.infrastructure.adapters.codex.assessment as client
from model_fit.assessment.validation import validate
from model_fit.infrastructure.adapters.codex.transport.assessment import execution


class SpeedBoundaryTests(unittest.TestCase):
    def test_native_output_schema_prevents_unknown_speed_recommendation(self):
        for speed in [None, "fast"]:
            with self.subTest(speed=speed):
                app = MagicMock()
                app.__enter__.return_value = app
                app.skill_file = Path("/fixture/SKILL.md")
                app.call.side_effect = [
                    {
                        "data": [
                            {
                                "skills": [
                                    {
                                        "name": "model-fit",
                                        "enabled": True,
                                        "path": str(app.skill_file),
                                    }
                                ]
                            }
                        ]
                    },
                    {"thread": {"id": "thread"}},
                    {"turn": {"id": "turn"}},
                ]
                app.wait_turn.return_value = "completed"
                app.events = []
                with patch.object(execution, "assessment_response", return_value={}):
                    execution.execute_assessment(
                        "rules",
                        "task",
                        "gpt-6.1-sol",
                        "low",
                        1,
                        None,
                        "codex",
                        lambda *a, _app=app, **kw: _app,
                        None,
                        active_profile={
                            "model": "gpt-6.1-sol",
                            "effort": "medium",
                            "speed": speed,
                        },
                    )
                schema = app.call.call_args_list[-1].args[1]["outputSchema"]
                self.assertEqual(
                    schema["properties"]["recommended_speed"]["type"],
                    "null" if speed is None else ["string", "null"],
                )
                self.assertEqual(
                    schema["properties"]["active_speed"]["type"],
                    "null" if speed is None else ["string", "null"],
                )

    def test_invalid_speed_has_distinct_safe_type_through_cli_boundary(self):
        active = {"model": "gpt-6.1-sol", "effort": "medium", "speed": None}
        output = {
            "active_model": active["model"],
            "active_effort": active["effort"],
            "active_speed": None,
            "decision": "recommend_stronger",
            "recommended_model": active["model"],
            "recommended_effort": "high",
            "recommended_speed": "fast",
            "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
            "official_guidance": "fixture guidance",
            "task_inference": "fixture task",
            "reason": "fixture reason",
        }
        with self.assertRaises(ValueError) as caught:
            validate(output, active, MagicMock())
        self.assertEqual(type(caught.exception).__name__, "UnknownSpeedChange")
        stdout, stderr = (io.StringIO(), io.StringIO())
        with (
            patch.object(cli.sys, "argv", ["model-fit"]),
            patch.object(
                cli.sys,
                "stdin",
                io.StringIO(json.dumps({"task": "fixture", "active_profile": active})),
            ),
            patch.object(cli, "assess", side_effect=caught.exception),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = cli.main()
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(stdout.getvalue())["decision"], "unknown")
        self.assertEqual(
            stderr.getvalue(), "model-fit triage error: UnknownSpeedChange\n"
        )
        self.assertNotIn(str(caught.exception), stderr.getvalue())
        result = subprocess.CompletedProcess(
            [], status, stdout=stdout.getvalue(), stderr=stderr.getvalue()
        )
        with (
            patch.object(client.subprocess, "run", return_value=result),
            self.assertRaises(ValueError) as propagated,
        ):
            client.triage({"active_profile": active})
        self.assertEqual(type(propagated.exception).__name__, "UnknownSpeedChange")
