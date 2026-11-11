"""Desktop completion scenarios."""

import io
import json
import os
import sys

from contextlib import redirect_stdout
from unittest.mock import patch

import vector_prime.entrypoints.hooks.instructions as HOOKS_INSTRUCTIONS
import vector_prime.entrypoints.hooks.native_contract as DESKTOP_CONFIGURATION
from vector_prime.entrypoints.hooks import operations
import vector_prime.infrastructure.adapters.filesystem.state as HANDOFF_STATE
import vector_prime.entrypoints.hooks.events.dispatch as EVENTS


from fixtures.autoswitch.desktop import DesktopHandoffCase


class CompletionTests(DesktopHandoffCase):
    def test_finished_unqueued_control_turn_releases_guard(self):
        state = {
            "phase": "ready",
            "source_turn_id": self.turn_id,
            "pending_assessment": None,
            "assessment_generation": "retained-generation",
        }
        HANDOFF_STATE.state_path(self.thread_id).parent.mkdir(
            parents=True, exist_ok=True
        )
        HANDOFF_STATE.write_state(HANDOFF_STATE.state_path(self.thread_id), state)
        event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "last_assistant_message": "Profile switch unavailable; use Sol medium",
        }
        self.assertIsNone(operations.guard_replay_answer(event))
        saved = HANDOFF_STATE.read_state(HANDOFF_STATE.state_path(self.thread_id))
        self.assertEqual(saved["phase"], "passed")
        self.assertEqual(saved["assessment_generation"], "retained-generation")
        self.assertNotIn("pending_assessment", saved)
        self.assertIsNone(
            operations.guard_tool(
                {**event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )

    def test_stop_does_not_clear_unknown_queue_attempt_or_other_turn(self):
        for phase, turn in [("attempting", self.turn_id), ("ready", "other-turn")]:
            state = {"phase": phase, "source_turn_id": self.turn_id}
            HANDOFF_STATE.state_path(self.thread_id).parent.mkdir(
                parents=True, exist_ok=True
            )
            HANDOFF_STATE.write_state(HANDOFF_STATE.state_path(self.thread_id), state)
            self.assertIsNone(
                operations.guard_replay_answer(
                    {
                        "session_id": self.thread_id,
                        "turn_id": turn,
                        "last_assistant_message": "finished",
                    }
                )
            )
            self.assertEqual(
                HANDOFF_STATE.read_state(HANDOFF_STATE.state_path(self.thread_id)),
                state,
            )

    def test_main_stop_emits_one_continuation_decision(self):
        event = dict(
            self.event,
            hook_event_name="Stop",
            turn_id="replay-turn",
            stop_hook_active=False,
            last_assistant_message="An unrelated answer",
        )
        output = io.StringIO()
        with (
            patch.dict(
                os.environ, {DESKTOP_CONFIGURATION.AUTO_THREAD_ENV: self.thread_id}
            ),
            patch("sys.stdin", io.StringIO(json.dumps(event))),
            patch.object(sys, "argv", ["desktop.py"]),
            patch.object(
                EVENTS,
                "guard_replay_answer",
                return_value={
                    "decision": "block",
                    "reason": HOOKS_INSTRUCTIONS.REPLAY_STOP_REASON,
                },
            ) as guard,
            redirect_stdout(output),
        ):
            self.assertEqual(EVENTS.handle_event(), 0)
        self.assertEqual(json.loads(output.getvalue())["decision"], "block")
        guard.assert_called_once_with(event)

    def test_stop_retries_only_unrelated_replay_answer(self):
        content, queued = self.stage_replay()
        event = dict(
            self.event,
            hook_event_name="Stop",
            turn_id="replay-turn",
            stop_hook_active=False,
            last_assistant_message="Done: closed the old #138 and #126",
        )
        with (
            patch.object(operations, "AppServerReader") as reader,
            patch(
                "vector_prime.entrypoints.hooks.operations.check_answer",
                return_value="unrelated",
            ) as classify,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                self.source_response(content),
                {
                    "data": [{"item": {"type": "userMessage", "content": queued}}],
                    "nextCursor": None,
                },
                {
                    "data": [{"item": {"type": "userMessage", "content": queued}}],
                    "nextCursor": None,
                },
            ]
            result = operations.guard_replay_answer(event)
        self.assertEqual(
            result,
            {"decision": "block", "reason": HOOKS_INSTRUCTIONS.REPLAY_STOP_REASON},
        )
        classify.assert_called_once_with(
            self.prompt,
            self.recommendation["task_inference"],
            event["last_assistant_message"],
        )
        event["stop_hook_active"] = True
        with patch.object(operations, "AppServerReader") as reader:
            self.assertIsNone(operations.guard_replay_answer(event))
            reader.assert_not_called()

    def test_stop_accepts_relevant_replay_answer(self):
        content, queued = self.stage_replay()
        event = dict(
            self.event,
            hook_event_name="Stop",
            turn_id="replay-turn",
            stop_hook_active=False,
            last_assistant_message="Checked backend #124; Reg.ru access is needed",
        )
        with (
            patch.object(operations, "AppServerReader") as reader,
            patch(
                "vector_prime.entrypoints.hooks.operations.check_answer",
                return_value="relevant",
            ) as classify,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                self.source_response(content),
                {
                    "data": [{"item": {"type": "userMessage", "content": queued}}],
                    "nextCursor": None,
                },
            ]
            self.assertIsNone(operations.guard_replay_answer(event))
        classify.assert_called_once()

    def test_stop_evaluates_the_correction_preserved_before_transfer(self):
        content = [
            {"type": "text", "text": self.prompt},
            {"type": "text", "text": "Give only a plan instead of implementation"},
        ]
        original, queued = self.stage_replay(content)
        event = dict(
            self.event,
            hook_event_name="Stop",
            turn_id="replay-turn",
            stop_hook_active=False,
            last_assistant_message="Implementation plan",
        )
        with (
            patch.object(operations, "AppServerReader") as reader,
            patch(
                "vector_prime.entrypoints.hooks.operations.check_answer",
                return_value="relevant",
            ) as classify,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                {
                    "data": [
                        {"item": {"type": "userMessage", "content": [item]}}
                        for item in original
                    ],
                    "nextCursor": None,
                },
                {
                    "data": [{"item": {"type": "userMessage", "content": queued}}],
                    "nextCursor": None,
                },
            ]
            self.assertIsNone(operations.guard_replay_answer(event))
        classify.assert_called_once_with(
            self.prompt + "\nGive only a plan instead of implementation",
            self.recommendation["task_inference"],
            "Implementation plan",
        )

    def test_stop_skips_multimodal_or_steered_replay(self):
        content = [
            {"type": "text", "text": self.prompt},
            {"type": "localImage", "path": "/tmp/reference.png"},
        ]
        original, queued = self.stage_replay(content)
        event = dict(
            self.event,
            hook_event_name="Stop",
            turn_id="replay-turn",
            stop_hook_active=False,
            last_assistant_message="Image answer",
        )
        with (
            patch.object(operations, "AppServerReader") as reader,
            patch("vector_prime.entrypoints.hooks.operations.check_answer") as classify,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                self.source_response(original),
                {
                    "data": [{"item": {"type": "userMessage", "content": queued}}],
                    "nextCursor": None,
                },
            ]
            self.assertIsNone(operations.guard_replay_answer(event))
            classify.assert_not_called()
        with (
            patch.object(operations, "AppServerReader") as reader,
            patch("vector_prime.entrypoints.hooks.operations.check_answer") as classify,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                self.source_response(original),
                {
                    "data": [
                        {"item": {"type": "userMessage", "content": queued}},
                        {
                            "item": {
                                "type": "userMessage",
                                "content": [{"type": "text", "text": "Clarification"}],
                            }
                        },
                    ],
                    "nextCursor": None,
                },
            ]
            self.assertIsNone(operations.guard_replay_answer(event))
            classify.assert_not_called()

    def test_stop_correction_is_discarded_when_hooks_are_revoked_during_evaluation(
        self,
    ):
        event = dict(
            self.event,
            hook_event_name="Stop",
            stop_hook_active=False,
            last_assistant_message="Old answer",
        )
        output = io.StringIO()
        with (
            patch.dict(
                os.environ, {DESKTOP_CONFIGURATION.AUTO_THREAD_ENV: self.thread_id}
            ),
            patch("sys.stdin", io.StringIO(json.dumps(event))),
            patch.object(
                EVENTS, "automatic_allowed", side_effect=[True, False]
            ) as admission,
            patch.object(
                EVENTS,
                "guard_replay_answer",
                return_value={"decision": "block", "reason": "stale correction"},
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(EVENTS.handle_event(check_admission=True), 0)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(admission.call_count, 2)

    def test_stop_correction_does_not_block_when_final_admission_is_unknown(self):
        event = dict(
            self.event,
            hook_event_name="Stop",
            stop_hook_active=False,
            last_assistant_message="Old answer",
        )
        output = io.StringIO()
        with (
            patch.dict(
                os.environ, {DESKTOP_CONFIGURATION.AUTO_THREAD_ENV: self.thread_id}
            ),
            patch("sys.stdin", io.StringIO(json.dumps(event))),
            patch.object(EVENTS, "automatic_allowed", side_effect=[True, None]),
            patch.object(EVENTS, "record_unavailable") as record,
            patch.object(
                EVENTS,
                "guard_replay_answer",
                return_value={"decision": "block", "reason": "stale correction"},
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(EVENTS.handle_event(check_admission=True), 0)
        self.assertNotIn("decision", json.loads(output.getvalue()))
        record.assert_called_once_with(self.thread_id, self.turn_id, "Stop")

    def test_stop_evaluator_failure_does_not_block_turn(self):
        event = dict(
            self.event,
            hook_event_name="Stop",
            turn_id="replay-turn",
            stop_hook_active=False,
            last_assistant_message="Answer",
        )
        output = io.StringIO()
        with (
            patch.dict(
                os.environ, {DESKTOP_CONFIGURATION.AUTO_THREAD_ENV: self.thread_id}
            ),
            patch("sys.stdin", io.StringIO(json.dumps(event))),
            patch.object(sys, "argv", ["desktop.py"]),
            patch.object(
                EVENTS, "guard_replay_answer", side_effect=RuntimeError("unavailable")
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(EVENTS.handle_event(), 0)
        self.assertEqual(output.getvalue(), "")
        audit = (
            (self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        self.assertEqual(json.loads(audit[-1])["outcome"], "auto_error:RuntimeError")
