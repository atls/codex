import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch
from jsonschema import Draft202012Validator

import vector_prime.entrypoints.cli.assess as cli
import vector_prime.infrastructure.adapters.runtime.assessment as client
from vector_prime.application.assessment.decision import validate
from vector_prime.infrastructure.adapters.codex.transport.assessment import execution


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
                for field in ("recommended_speed", "active_speed"):
                    validator = Draft202012Validator(schema["properties"][field])
                    self.assertTrue(validator.is_valid(None))
                    self.assertEqual(validator.is_valid("fast"), speed is not None)
                    self.assertFalse(validator.is_valid(True))

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


def test_sampling_speed_is_scoped_to_native_turn_and_model(tmp_path, monkeypatch):
    import sqlite3
    import time
    from vector_prime.infrastructure.adapters.codex.history import observed_speed

    monkeypatch.setenv("CODEX_SQLITE_HOME", str(tmp_path))
    assert observed_speed("thread", "source", "sol") is None
    assert not (tmp_path / "logs_2.sqlite").exists()
    with sqlite3.connect(tmp_path / "logs_2.sqlite") as db:
        db.execute(
            "CREATE TABLE logs(id INTEGER PRIMARY KEY, ts INTEGER, thread_id TEXT, target TEXT, feedback_log_body TEXT)"
        )
        for thread, turn, model, tier in [
            ("thread", "source", "sol", "default"),
            ("thread", "replay", "sol", "priority"),
            ("thread", "source", "other", "priority"),
            ("other", "source", "sol", "priority"),
            ("thread", "unknown", "sol", "flex"),
        ]:
            body = f'run_sampling_request{{turn_id={turn} model={model} cwd=/fixture}} tags_json={{"service_tier":"{tier}"}}'
            db.execute(
                "INSERT INTO logs(ts,thread_id,target,feedback_log_body) VALUES (?,?,?,?)",
                (int(time.time()), thread, "feedback_tags", body),
            )
    assert observed_speed("thread", "source", "sol") == "standard"
    assert observed_speed("thread", "replay", "sol") == "fast"
    assert observed_speed("thread", "unknown", "sol") is None
    assert observed_speed("thread", None, "sol") is None
