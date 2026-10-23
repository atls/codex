"""Model Fit hook regression checks."""

import io
import json
import os
import select
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hook_case import AUTO, SCRIPTS, STATE, AutoSwitchCase


class ToolGuardTests(AutoSwitchCase):
    def test_control_turn_allows_only_profile_switch_and_exact_queue_command(self):
        self.stage()
        event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "mcp__codex_app__send_message_to_thread",
            "tool_input": {
                "threadId": self.thread_id,
                "model": "gpt-6-sol",
                "thinking": "medium",
                "prompt": AUTO.CONTROL_PROMPT,
            },
        }
        self.assertIsNone(AUTO.guard_tool(event))
        event["tool_name"] = "Bash"
        event["tool_input"] = {
            "command": AUTO.queue_command(self.thread_id, self.turn_id)
        }
        self.assertIsNone(AUTO.guard_tool(event))
        event["tool_input"] = {"command": "python3 -c 'print(1)'"}
        self.assertEqual(
            AUTO.guard_tool(event)["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        event["turn_id"] = "another-turn"
        self.assertIsNone(AUTO.guard_tool(event))

    def test_tool_guard_denies_immediately_during_state_lock_contention(self):
        self.stage()
        event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        with STATE.locked_state(
            self.thread_id, operation="queue", turn_id="holder-turn"
        ):
            started = time.monotonic()
            result = AUTO.guard_tool(event)
            elapsed = time.monotonic() - started
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "занято", result["hookSpecificOutput"]["permissionDecisionReason"]
        )
        self.assertLess(elapsed, 1)
        audit = (
            (Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        failure = json.loads(audit[-1])
        self.assertEqual(failure["outcome"], "auto_guard_block")
        self.assertEqual(failure["details"]["reason_code"], "state_lock_busy")
        self.assertEqual(failure["details"]["state_phase"], "ready")
        self.assertEqual(failure["details"]["holder_pid"], os.getpid())
        self.assertEqual(failure["details"]["holder_operation"], "queue")
        self.assertEqual(failure["details"]["holder_turn_id"], "holder-turn")
        self.assertGreater(failure["details"]["holder_acquired_at_ns"], 0)
        self.assertNotIn(event["tool_input"]["command"], "\n".join(audit))
        self.assertFalse(STATE.lock_owner(self.thread_id)["holder_observed"])

    def test_tool_guard_allows_passed_turn_during_state_lock_contention(self):
        path = self.stage()
        STATE.write_state(path, {"phase": "passed", "source_turn_id": self.turn_id})
        event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        with STATE.locked_state(
            self.thread_id, operation="prompt_submit", turn_id="holder-turn"
        ):
            started = time.monotonic()
            result = AUTO.guard_tool(event)
            elapsed = time.monotonic() - started
        self.assertIsNone(result)
        self.assertLess(elapsed, 1)
        audit = (
            (Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        recovered = json.loads(audit[-1])
        self.assertEqual(recovered["outcome"], "auto_guard_lock_contention")
        self.assertEqual(recovered["details"]["reason_code"], "passed_same_turn")
        self.assertEqual(recovered["details"]["holder_operation"], "prompt_submit")

    def test_lock_contention_identifies_other_process(self):
        self.stage()
        script = (
            "import sys; "
            f"sys.path.insert(0, {str(SCRIPTS)!r}); "
            "from model_fit.state import locked_state; "
            "\nwith locked_state('test-thread', operation='queue', turn_id='holder-turn'):"
            "\n print('locked', flush=True)"
            "\n sys.stdin.readline()"
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy(),
        )
        try:
            self.assertTrue(select.select([holder.stdout], [], [], 3)[0])
            self.assertEqual(holder.stdout.readline().strip(), "locked")
            event = {
                "session_id": self.thread_id,
                "turn_id": self.turn_id,
                "tool_name": "Bash",
                "tool_input": {"command": "echo work"},
            }
            self.assertEqual(
                AUTO.guard_tool(event)["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
            audit = (
                (
                    Path(self.temporary.name)
                    / ".tmp/model-fit-hook-audit/test-thread.jsonl"
                )
                .read_text()
                .splitlines()
            )
            self.assertEqual(json.loads(audit[-1])["details"]["holder_pid"], holder.pid)
            self.assertEqual(
                json.loads(audit[-1])["details"]["holder_operation"], "queue"
            )
        finally:
            if holder.poll() is None:
                holder.communicate("\n", timeout=3)

    def test_lock_metadata_drops_invalid_turn_id(self):
        with STATE.locked_state(
            self.thread_id,
            operation="pre_tool_use",
            turn_id={"text": "private request"},
        ):
            lock_text = (
                STATE.state_path(self.thread_id).with_suffix(".lock").read_text()
            )
            self.assertIsNone(json.loads(lock_text)["turn_id"])
            self.assertNotIn("private request", lock_text)

    def test_lock_metadata_never_writes_through_symlink(self):
        victim = Path(self.temporary.name) / "victim.txt"
        victim.write_text("keep")
        lock_path = STATE.state_path(self.thread_id).with_suffix(".lock")
        lock_path.parent.mkdir(parents=True)
        lock_path.symlink_to(victim)
        with self.assertRaises(OSError):
            with STATE.locked_state(
                self.thread_id, operation="queue", turn_id=self.turn_id
            ):
                pass
        self.assertEqual(victim.read_text(), "keep")

    def test_tool_guard_denies_other_turn_during_passed_state_lock_contention(self):
        path = self.stage()
        STATE.write_state(path, {"phase": "passed", "source_turn_id": "another-turn"})
        event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        with STATE.locked_state(self.thread_id):
            result = AUTO.guard_tool(event)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_tool_guard_error_uses_pre_tool_use_denial_shape(self):
        event = {
            "hook_event_name": "PreToolUse",
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        output = io.StringIO()
        with (
            patch.dict(os.environ, {AUTO.AUTO_THREAD_ENV: self.thread_id}),
            patch("sys.argv", ["hook.py"]),
            patch("sys.stdin", io.StringIO(json.dumps(event))),
            patch.object(AUTO, "guard_tool", side_effect=OSError("state unavailable")),
            redirect_stdout(output),
        ):
            self.assertEqual(AUTO.main(), 0)
        self.assertEqual(
            json.loads(output.getvalue())["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        audit = (
            (Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        self.assertEqual(json.loads(audit[-1])["outcome"], "auto_error:OSError")
        self.assertEqual(json.loads(audit[-1])["details"]["hook_event"], "PreToolUse")

    def test_control_turn_cannot_call_more_tools_after_queue(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
        STATE.write_state(path, state)
        event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": AUTO.queue_command(self.thread_id, self.turn_id)},
        }
        self.assertEqual(
            AUTO.guard_tool(event)["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_steer_in_queued_source_turn_preserves_tool_guard(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
        STATE.write_state(path, state)
        steered = dict(self.event, prompt="Покажи бэклог")
        with patch.object(AUTO, "AppServerReader") as reader:
            self.assertEqual(AUTO.prepare(steered)["decision"], "block")
            reader.assert_not_called()
        self.assertEqual(STATE.read_state(path)["phase"], "queued")
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
