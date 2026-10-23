"""Model Fit hook regression checks."""

import os
from unittest.mock import patch

from hook_case import AUTO, INPUT, STATE, AutoSwitchCase
from model_fit import queue as QUEUE


class QueueFailureTests(AutoSwitchCase):
    def test_full_replay_is_admitted_on_target_without_retriage(self):
        path = self.stage()
        queued = INPUT.replay_input(
            [
                {"type": "text", "text": self.prompt},
                {"type": "image", "url": "data:image/png;base64,aW1hZ2U="},
            ],
            "nonce",
        )
        prompt = INPUT.input_text(queued)
        state = STATE.read_state(path)
        state.update(
            phase="queued",
            queued_submission_id="queued-1",
            queued_at=100,
            queued_prompt_digest=INPUT.prompt_digest(prompt),
            queued_input_digest=INPUT.input_digest(queued),
        )
        STATE.write_state(path, state)
        with (
            patch.object(AUTO, "AppServerReader") as reader,
            patch.object(
                AUTO,
                "session_input",
                return_value={
                    "active_profile": {
                        "model": "gpt-6-sol",
                        "effort": "medium",
                        "speed": None,
                    },
                },
            ),
            patch.object(AUTO, "triage") as triage,
        ):
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [{"data": [], "nextCursor": None}]
            result = AUTO.prepare(
                dict(self.event, prompt=prompt, turn_id="replay-turn")
            )
            triage.assert_not_called()
        self.assertIn("hookSpecificOutput", result)
        self.assertEqual(STATE.read_state(path)["replay_turn_id"], "replay-turn")

    def test_queue_reply_with_missing_attachment_is_removed(self):
        path = self.stage()
        content = [
            {"type": "text", "text": self.prompt},
            {"type": "image", "url": "data:image/png;base64,aW1hZ2U="},
        ]
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(content),
                self.queue_receipt([content[0]]),
                {"deleted": True},
            ]
            with self.assertRaisesRegex(ValueError, "complete user input"):
                AUTO.enqueue(self.thread_id, self.turn_id)
            self.assertEqual(app.call.call_args_list[-1].args[0], "thread/queue/delete")
        self.assertEqual(STATE.read_state(path)["phase"], "rejected")

    def test_same_text_in_new_turn_replaces_pending_native_message(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
        STATE.write_state(path, state)
        with (
            patch.object(
                AUTO,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(AUTO, "triage", return_value={"decision": "keep"}),
            patch.object(AUTO, "AppServerReader") as reader,
        ):
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"data": [{"id": "queued-1"}], "nextCursor": None},
                {"deleted": True},
            ]
            self.assertIsNone(AUTO.prepare(dict(self.event, turn_id="new-turn")))
            self.assertEqual(
                [c.args[0] for c in app.call.call_args_list],
                [
                    "thread/queue/list",
                    "thread/queue/delete",
                ],
            )
        self.assertEqual(STATE.read_state(path)["phase"], "passed")

    def test_input_mismatch_with_uncertain_removal_cannot_be_retried(self):
        path = self.stage()
        content = [
            {"type": "text", "text": self.prompt},
            {"type": "image", "url": "image"},
        ]
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(content),
                self.queue_receipt([content[0]]),
                {"deleted": False},
            ]
            with self.assertRaisesRegex(RuntimeError, "could not be removed"):
                AUTO.enqueue(self.thread_id, self.turn_id)
        self.assertEqual(STATE.read_state(path)["phase"], "attempting")
        self.assertEqual(STATE.read_state(path)["queued_submission_id"], "queued-1")
        with self.assertRaisesRegex(RuntimeError, "do not retry"):
            AUTO.enqueue(self.thread_id, self.turn_id)

    def test_terminal_turn_with_lost_attachment_does_not_confirm_replay(self):
        queued = INPUT.replay_input(
            [
                {"type": "text", "text": self.prompt},
                {"type": "image", "url": "same-image"},
            ],
            "nonce",
        )
        state = {
            "source_turn_id": self.turn_id,
            "queued_at": 100,
            "queued_input_digest": INPUT.input_digest(queued),
        }
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {
                    "data": [
                        {"id": "replay-turn", "startedAt": 101, "status": "completed"}
                    ]
                },
                self.source_response([queued[0]]),
            ]
            self.assertFalse(QUEUE.replay_finished(app, self.thread_id, state))

    def test_uncertain_queue_attempt_is_not_retried(self):
        path = self.stage()
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                TimeoutError("unknown outcome"),
            ]
            with self.assertRaises(TimeoutError):
                AUTO.enqueue(self.thread_id, self.turn_id)
        state = STATE.read_state(path)
        self.assertEqual(state["phase"], "attempting")
        self.assertNotIn("prompt", state)
        with patch.object(AUTO, "AppServerReader") as reader:
            with self.assertRaisesRegex(RuntimeError, "do not retry"):
                AUTO.enqueue(self.thread_id, self.turn_id)
            reader.assert_not_called()

    def test_explicit_queue_rejection_clears_handoff(self):
        path = self.stage()
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                AUTO.AppServerRPCError(
                    "thread/queue/add: queue cannot contain more than 100 submissions"
                ),
            ]
            with self.assertRaises(AUTO.AppServerRPCError):
                AUTO.enqueue(self.thread_id, self.turn_id)
        self.assertEqual(STATE.read_state(path)["phase"], "rejected")
        guard_event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        self.assertEqual(
            AUTO.guard_tool(guard_event)["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            AUTO.enqueue(self.thread_id, self.turn_id)
        self.assertEqual(AUTO.prepare(self.event)["decision"], "block")
        next_event = dict(self.event, turn_id="new-turn")
        with (
            patch.object(
                AUTO,
                "session_input",
                return_value={
                    "task": self.prompt,
                    "active_profile": self.active,
                },
            ),
            patch.object(AUTO, "triage", return_value={"decision": "keep"}),
        ):
            self.assertIsNone(AUTO.prepare(next_event))
        self.assertEqual(STATE.read_state(path)["phase"], "passed")

    def test_json_rpc_rejection_has_distinct_exception(self):
        reader = object.__new__(AUTO.AppServerReader)
        reader.next_id = 0
        with (
            patch.object(reader, "send"),
            patch.object(
                reader,
                "read",
                return_value={
                    "id": 0,
                    "error": {"code": -32000, "message": "queue full"},
                },
            ),
        ):
            with self.assertRaisesRegex(AUTO.AppServerRPCError, "queue full"):
                reader.call("thread/queue/add", {}, 1)

    def test_expired_handoff_cannot_queue_old_task(self):
        path = self.stage()
        state = STATE.read_state(path)
        state["created_at"] = 0
        STATE.write_state(path, state)
        with patch.object(AUTO, "AppServerReader") as reader:
            with self.assertRaisesRegex(ValueError, "expired"):
                AUTO.enqueue(self.thread_id, self.turn_id)
            reader.assert_not_called()

    def test_other_thread_cannot_queue_handoff(self):
        self.stage()
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "another-thread"}):
            with self.assertRaisesRegex(ValueError, "target Desktop thread"):
                AUTO.enqueue(self.thread_id, self.turn_id)
