"""Model Fit hook regression checks."""

import io
import json
import os
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hook_case import AUTO, STATE, AutoSwitchCase


class SelectionTests(AutoSwitchCase):
    def test_recommendation_stages_exact_prompt_for_control_only_turn(self):
        request = {"task": self.prompt, "active_profile": self.active}
        with (
            patch.object(AUTO, "session_input", return_value=request),
            patch.object(AUTO, "triage", return_value=self.recommendation),
            patch.object(AUTO, "AppServerReader") as reader,
        ):
            reader.return_value.__enter__.return_value.call.return_value = {
                "data": [],
                "nextCursor": None,
            }
            result = AUTO.prepare(self.event)
        instruction = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("model=gpt-6-sol, thinking=medium", instruction)
        self.assertIn("queue --thread-id", instruction)
        self.assertIn("не выполняй исходную задачу", instruction)
        state = STATE.read_state(STATE.state_path(self.thread_id))
        self.assertEqual(state["prompt"], self.prompt)
        self.assertEqual(state["source_turn_id"], self.turn_id)
        self.assertEqual(STATE.state_path(self.thread_id).stat().st_mode & 0o777, 0o600)

    def test_keep_never_stages_or_switches(self):
        request = {"task": self.prompt, "active_profile": self.active}
        with (
            patch.object(AUTO, "session_input", return_value=request),
            patch.object(AUTO, "triage", return_value={"decision": "keep"}),
            patch.object(AUTO, "AppServerReader") as reader,
        ):
            self.assertIsNone(AUTO.prepare(self.event))
            reader.assert_not_called()
        self.assertEqual(
            STATE.read_state(STATE.state_path(self.thread_id))["phase"], "passed"
        )

    def test_steering_after_keep_does_not_stage_new_handoff_or_block_tools(self):
        with (
            patch.object(
                AUTO,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(AUTO, "triage", return_value={"decision": "keep"}),
        ):
            self.assertIsNone(AUTO.prepare(self.event))
        steer = dict(self.event, prompt="Также сократи ссылку до Подробнее")
        with (
            patch.object(AUTO, "session_input") as session,
            patch.object(AUTO, "triage", return_value=self.recommendation) as triage,
            patch.object(AUTO, "AppServerReader") as reader,
        ):
            self.assertIsNone(AUTO.prepare(steer))
            session.assert_not_called()
            triage.assert_not_called()
            reader.assert_not_called()
        self.assertIsNone(
            AUTO.guard_tool(
                {
                    "session_id": self.thread_id,
                    "turn_id": self.turn_id,
                    "tool_name": "Bash",
                    "tool_input": {"command": "echo continued"},
                }
            )
        )
        state = STATE.read_state(STATE.state_path(self.thread_id))
        self.assertEqual(state, {"phase": "passed", "source_turn_id": self.turn_id})

    def test_next_turn_after_keep_runs_triage_again(self):
        with (
            patch.object(
                AUTO,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(AUTO, "triage", return_value={"decision": "keep"}),
        ):
            self.assertIsNone(AUTO.prepare(self.event))
        with (
            patch.object(
                AUTO,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(AUTO, "triage", return_value=self.recommendation) as triage,
            patch.object(AUTO, "AppServerReader") as reader,
        ):
            reader.return_value.__enter__.return_value.call.return_value = {
                "data": [],
                "nextCursor": None,
            }
            result = AUTO.prepare(dict(self.event, turn_id="next-turn"))
            triage.assert_called_once()
        self.assertIn("hookSpecificOutput", result)
        self.assertEqual(
            STATE.read_state(STATE.state_path(self.thread_id))["phase"], "ready"
        )

    def test_steering_after_unknown_does_not_reclassify_running_work(self):
        with (
            patch.object(
                AUTO,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(AUTO, "triage", return_value={"decision": "unknown"}),
        ):
            self.assertIn("systemMessage", AUTO.prepare(self.event))
        with patch.object(AUTO, "triage") as triage:
            self.assertIsNone(AUTO.prepare(dict(self.event, prompt="Уточнение")))
            triage.assert_not_called()

    def test_steer_in_ready_source_turn_preserves_tool_guard(self):
        path = self.stage()
        steered = dict(self.event, prompt="Покажи бэклог")
        self.assertEqual(AUTO.prepare(steered)["decision"], "block")
        self.assertEqual(STATE.read_state(path)["phase"], "ready")
        tool_event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        self.assertEqual(
            AUTO.guard_tool(tool_event)["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        audit = (
            (Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        self.assertIn("technical_turn_steered", "\n".join(audit))
        self.assertEqual(
            json.loads(audit[-1])["details"]["reason_code"],
            "technical_turn_tool_denied",
        )

    def test_triage_timeout_blocks_subject_turn_and_records_failure(self):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {AUTO.AUTO_THREAD_ENV: self.thread_id}),
            patch("sys.argv", ["hook.py"]),
            patch("sys.stdin", io.StringIO(json.dumps(self.event))),
            patch.object(
                AUTO, "prepare", side_effect=subprocess.TimeoutExpired("triage", 45)
            ),
            patch.object(AUTO, "record_audit") as audit,
            redirect_stdout(output),
        ):
            self.assertEqual(AUTO.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["decision"], "block")
        self.assertIn("TimeoutExpired", audit.call_args_list[-1].args[2])
