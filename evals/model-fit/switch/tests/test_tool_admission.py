"""Desktop tool admission scenarios."""

import io
import json
import os
import time

from contextlib import redirect_stdout
from unittest.mock import patch

from fixtures.autoswitch.assessment import evaluate_request
from fixtures.autoswitch.lock import held_lock
import vector_prime.entrypoints.hooks.instructions as HOOKS_INSTRUCTIONS
import vector_prime.entrypoints.hooks.native_contract as DESKTOP_CONFIGURATION
from vector_prime.entrypoints.hooks import operations
import vector_prime.infrastructure.adapters.filesystem.state as HANDOFF_STATE
import vector_prime.entrypoints.hooks.events.dispatch as EVENTS


from fixtures.autoswitch.desktop import DesktopHandoffCase


class ToolAdmissionTests(DesktopHandoffCase):
    def test_steer_in_ready_source_turn_preserves_tool_guard(self):
        path = self.stage()
        steered = dict(self.event, prompt="Show the backlog")
        self.assertIn(
            "additionalContext", self.prepare_ready(steered)["hookSpecificOutput"]
        )
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "ready")
        tool_event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        self.assertEqual(
            operations.guard_tool(tool_event)["hookSpecificOutput"][
                "permissionDecision"
            ],
            "deny",
        )
        audit = (
            (self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        self.assertIn("auto_handoff_continued", "\n".join(audit))
        self.assertEqual(
            json.loads(audit[-1])["details"]["reason_code"],
            "technical_turn_tool_denied",
        )

    def test_native_guard_binds_corrupted_transfer_ids_to_ready_state(self):
        path = self.stage(target_model="gpt-6.1-sol")
        original = HANDOFF_STATE.read_state(path)
        switch = {
            **self.event,
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__codex_app__send_message_to_thread",
            "tool_input": {
                "threadId": "11111111-1111-7111-8111-111111111111",
                "model": "gpt-6.1-sol",
                "thinking": "medium",
                "prompt": HOOKS_INSTRUCTIONS.CONTROL_PROMPT,
            },
        }
        bound = operations.guard_tool(switch)["hookSpecificOutput"]
        self.assertEqual(bound["permissionDecision"], "allow")
        self.assertEqual(
            bound["updatedInput"],
            {
                "threadId": self.thread_id,
                "model": "gpt-6.1-sol",
                "thinking": "medium",
                "prompt": HOOKS_INSTRUCTIONS.CONTROL_PROMPT,
            },
        )
        wrong_command = HOOKS_INSTRUCTIONS.queue_command(
            "11111111-1111-7112-8111-111111111111", "wrong-turn"
        )
        queued = operations.guard_tool(
            {**switch, "tool_name": "Bash", "tool_input": {"command": wrong_command}}
        )
        self.assertEqual(
            queued["hookSpecificOutput"]["updatedInput"]["command"],
            HOOKS_INSTRUCTIONS.queue_command(self.thread_id, self.turn_id),
        )
        persisted = HANDOFF_STATE.read_state(path)
        persisted.pop("transfer_authorized_at")
        self.assertEqual(persisted, original)
        for command in (wrong_command + "; touch forbidden", "echo " + wrong_command):
            denied = operations.guard_tool(
                {**switch, "tool_name": "Bash", "tool_input": {"command": command}}
            )
            self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            operations.guard_tool({**switch, "turn_id": "another-turn"})[
                "hookSpecificOutput"
            ]["permissionDecision"],
            "deny",
        )

    def test_transfer_authorization_still_expires_without_another_native_callback(self):
        path = self.stage()
        event = {
            **self.event,
            "tool_name": "Bash",
            "tool_input": {
                "command": HOOKS_INSTRUCTIONS.queue_command(
                    self.thread_id, self.turn_id
                )
            },
        }
        with patch.object(operations.time, "time", return_value=4000):
            self.assertIsNone(operations.guard_tool(event))
        before = path.read_bytes()
        with (
            patch.object(operations.time, "time", return_value=4301),
            self.assertRaisesRegex(ValueError, "expired"),
        ):
            operations.enqueue_handoff(self.thread_id, self.turn_id)
        self.assertEqual(path.read_bytes(), before)

    def test_native_transfer_authorization_cannot_overwrite_a_new_submission(self):
        path = self.stage()
        replacement = {
            "phase": "submitted",
            "source_turn_id": "new-source",
            "assessment_generation": "new-generation",
        }

        def changed(*args):
            HANDOFF_STATE.write_state(path, replacement)
            return True

        with patch.object(
            operations.NativeTransferTools, "matches_queue", side_effect=changed
        ):
            result = operations.guard_tool(
                {
                    **self.event,
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": HOOKS_INSTRUCTIONS.queue_command(
                            self.thread_id, self.turn_id
                        )
                    },
                }
            )
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(HANDOFF_STATE.read_state(path), replacement)

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
                "prompt": HOOKS_INSTRUCTIONS.CONTROL_PROMPT,
            },
        }
        self.assertIsNone(operations.guard_tool(event))
        event["tool_name"] = "Bash"
        event["tool_input"] = {
            "command": HOOKS_INSTRUCTIONS.queue_command(self.thread_id, self.turn_id)
        }
        self.assertIsNone(operations.guard_tool(event))
        event["tool_input"] = {"command": "python3 -c 'print(1)'"}
        self.assertEqual(
            operations.guard_tool(event)["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        event["turn_id"] = "another-turn"
        self.assertIsNone(operations.guard_tool(event))

    def test_desktop_profile_tool_alias_preserves_exact_handoff_arguments(self):
        self.stage()
        arguments = {
            "threadId": self.thread_id,
            "model": "gpt-6-sol",
            "thinking": "medium",
            "prompt": HOOKS_INSTRUCTIONS.CONTROL_PROMPT,
        }
        for tool in (
            "mcp__codex_app__send_message_to_thread",
            "codex_appsend_message_to_thread",
        ):
            event = {
                "session_id": self.thread_id,
                "turn_id": self.turn_id,
                "tool_name": tool,
                "tool_input": arguments,
            }
            with self.subTest(tool=tool):
                self.assertIsNone(operations.guard_tool(event))
            for field in arguments:
                with self.subTest(tool=tool, wrong=field):
                    wrong = dict(event, tool_input=dict(arguments, **{field: "wrong"}))
                    output = operations.guard_tool(wrong)["hookSpecificOutput"]
                    self.assertEqual(
                        output["permissionDecision"],
                        "allow" if field == "threadId" else "deny",
                    )
                    if field == "threadId":
                        self.assertEqual(output["updatedInput"], arguments)
        event["tool_name"] = "other_codex_appsend_message_to_thread"
        self.assertEqual(
            operations.guard_tool(event)["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

    def test_tool_guard_denies_immediately_during_state_lock_contention(self):
        self.stage()
        event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        with HANDOFF_STATE.locked_state(
            self.thread_id, operation="queue", turn_id="holder-turn"
        ):
            started = time.monotonic()
            result = operations.guard_tool(event)
            elapsed = time.monotonic() - started
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "busy", result["hookSpecificOutput"]["permissionDecisionReason"].casefold()
        )
        self.assertLess(elapsed, 1)
        audit = (
            (self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl")
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
        self.assertFalse(HANDOFF_STATE.lock_owner(self.thread_id)["holder_observed"])

    def test_tool_guard_allows_passed_turn_during_state_lock_contention(self):
        path = self.stage()
        HANDOFF_STATE.write_state(
            path, {"phase": "passed", "source_turn_id": self.turn_id}
        )
        event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        with HANDOFF_STATE.locked_state(
            self.thread_id, operation="prompt_submit", turn_id="holder-turn"
        ):
            started = time.monotonic()
            result = operations.guard_tool(event)
            elapsed = time.monotonic() - started
        self.assertIsNone(result)
        self.assertLess(elapsed, 1)
        audit = (
            (self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        recovered = json.loads(audit[-1])
        self.assertEqual(recovered["outcome"], "auto_guard_lock_contention")
        self.assertEqual(recovered["details"]["reason_code"], "passed_same_turn")
        self.assertEqual(recovered["details"]["holder_operation"], "prompt_submit")

    def test_confirmed_replay_has_same_permission_during_lock_contention(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.update(
            phase="queued",
            replay_turn_id="replay-turn",
            queued_submission_id="queue-id",
        )
        HANDOFF_STATE.write_state(path, state)
        event = {
            "session_id": self.thread_id,
            "turn_id": "replay-turn",
            "tool_name": "Bash",
            "tool_input": {"command": "pwd"},
        }
        self.assertIsNone(operations.guard_tool(event))
        with HANDOFF_STATE.locked_state(
            self.thread_id, operation="pre_tool_use", turn_id="replay-turn"
        ):
            self.assertIsNone(operations.guard_tool(event))
        self.assertEqual(HANDOFF_STATE.read_state(path), state)
        audit = self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl"
        self.assertEqual(
            json.loads(audit.read_text().splitlines()[-1])["details"]["reason_code"],
            "confirmed_replay_same_turn",
        )

    def test_contention_keeps_unconfirmed_and_source_turns_protected(self):
        path = self.stage()
        for phase, replay, turn in [
            ("queued", None, "replay-turn"),
            ("queued", "replay-turn", self.turn_id),
            ("queued", "replay-turn", "other-turn"),
            ("attempting", "replay-turn", "replay-turn"),
        ]:
            state = HANDOFF_STATE.read_state(path)
            state.update(phase=phase, replay_turn_id=replay)
            HANDOFF_STATE.write_state(path, state)
            with (
                self.subTest(phase=phase, replay=replay, turn=turn),
                HANDOFF_STATE.locked_state(self.thread_id),
            ):
                result = operations.guard_tool(
                    {
                        "session_id": self.thread_id,
                        "turn_id": turn,
                        "tool_name": "Bash",
                        "tool_input": {"command": "pwd"},
                    }
                )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_lock_contention_identifies_other_process(self):
        self.stage()
        with held_lock(
            self.thread_id, operation="queue", turn_id="holder-turn"
        ) as holder_pid:
            event = {
                "session_id": self.thread_id,
                "turn_id": self.turn_id,
                "tool_name": "Bash",
                "tool_input": {"command": "echo work"},
            }
            self.assertEqual(
                operations.guard_tool(event)["hookSpecificOutput"][
                    "permissionDecision"
                ],
                "deny",
            )
            audit = (
                (self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl")
                .read_text()
                .splitlines()
            )
            self.assertEqual(json.loads(audit[-1])["details"]["holder_pid"], holder_pid)
            self.assertEqual(
                json.loads(audit[-1])["details"]["holder_operation"], "queue"
            )

    def test_lock_metadata_drops_invalid_turn_id(self):
        with HANDOFF_STATE.locked_state(
            self.thread_id,
            operation="pre_tool_use",
            turn_id={"text": "private request"},
        ):
            lock_text = (
                HANDOFF_STATE.state_path(self.thread_id)
                .with_suffix(".lock")
                .read_text()
            )
            self.assertIsNone(json.loads(lock_text)["turn_id"])
            self.assertNotIn("private request", lock_text)

    def test_lock_metadata_never_writes_through_symlink(self):
        victim = self.home / "victim.txt"
        victim.write_text("keep")
        lock_path = HANDOFF_STATE.state_path(self.thread_id).with_suffix(".lock")
        lock_path.parent.mkdir(parents=True)
        lock_path.symlink_to(victim)
        with self.assertRaises(OSError):
            with HANDOFF_STATE.locked_state(
                self.thread_id, operation="queue", turn_id=self.turn_id
            ):
                pass
        self.assertEqual(victim.read_text(), "keep")

    def test_tool_guard_denies_other_turn_during_passed_state_lock_contention(self):
        path = self.stage()
        HANDOFF_STATE.write_state(
            path, {"phase": "passed", "source_turn_id": "another-turn"}
        )
        event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        with HANDOFF_STATE.locked_state(self.thread_id):
            result = operations.guard_tool(event)
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
            patch.dict(
                os.environ, {DESKTOP_CONFIGURATION.AUTO_THREAD_ENV: self.thread_id}
            ),
            patch("sys.argv", ["desktop.py"]),
            patch("sys.stdin", io.StringIO(json.dumps(event))),
            patch.object(
                EVENTS, "guard_tool", side_effect=OSError("state unavailable")
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(EVENTS.handle_event(), 0)
        self.assertEqual(
            json.loads(output.getvalue())["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        audit = (
            (self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        self.assertEqual(json.loads(audit[-1])["outcome"], "auto_error:OSError")
        self.assertEqual(json.loads(audit[-1])["details"]["hook_event"], "PreToolUse")

    def test_control_turn_cannot_call_more_tools_after_queue(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.pop("prompt")
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
        HANDOFF_STATE.write_state(path, state)
        event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {
                "command": HOOKS_INSTRUCTIONS.queue_command(
                    self.thread_id, self.turn_id
                )
            },
        }
        self.assertEqual(
            operations.guard_tool(event)["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

    def test_steer_in_queued_source_turn_preserves_tool_guard(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.pop("prompt")
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
        HANDOFF_STATE.write_state(path, state)
        steered = dict(self.event, prompt="Show the backlog")
        with patch.object(operations, "AppServerReader") as reader:
            self.assertEqual(evaluate_request(steered)["decision"], "block")
            reader.assert_not_called()
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "queued")
        tool_event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        self.assertEqual(
            operations.guard_tool(tool_event)["hookSpecificOutput"][
                "permissionDecision"
            ],
            "deny",
        )
