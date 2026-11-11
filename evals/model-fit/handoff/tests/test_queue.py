"""Desktop queue scenarios."""

import io
import json
import os

from contextlib import redirect_stderr
from unittest.mock import patch

from fixtures.autoswitch.assessment import evaluate_request
import vector_prime.entrypoints.hooks.instructions as HOOKS_INSTRUCTIONS
from vector_prime.application.handoff.exceptions.queue_rejected import QueueRejected
from vector_prime.entrypoints.hooks import operations
import vector_prime.application.submission.helpers.content as HANDOFF_INPUT
import vector_prime.infrastructure.adapters.codex.transport.connection as CODEX_CONNECTION
import vector_prime.infrastructure.adapters.filesystem.state as HANDOFF_STATE
import vector_prime.entrypoints.hooks.handlers.queue as QUEUE


from fixtures.autoswitch.desktop import DesktopHandoffCase


class QueueTests(DesktopHandoffCase):
    def test_control_message_is_not_replayed_as_user_work(self):
        path = self.stage()
        evaluate_request(
            dict(
                self.event,
                turn_id="control-turn",
                prompt=HOOKS_INSTRUCTIONS.CONTROL_PROMPT,
            )
        )
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                self.source_response(
                    [{"type": "text", "text": HOOKS_INSTRUCTIONS.CONTROL_PROMPT}]
                ),
                self.queue_receipt(),
            ]
            self.assertEqual(
                operations.enqueue_handoff(self.thread_id, self.turn_id)["status"],
                "queued",
            )
            self.assertEqual(len(app.call.call_args_list[-1].args[1]["input"]), 1)
        self.assertNotIn("prompt", HANDOFF_STATE.read_state(path))

    def test_queue_requires_target_profile_and_matching_turn(self):
        path = self.stage()
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.return_value = {
                "thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}
            }
            with self.assertRaisesRegex(ValueError, "Target profile"):
                operations.enqueue_handoff(self.thread_id, self.turn_id)
            self.assertEqual(app.call.call_count, 1)
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "ready")
        with self.assertRaisesRegex(ValueError, "No matching"):
            operations.enqueue_handoff(self.thread_id, "other-turn")
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "ready")

    def test_queue_runs_once_and_drops_prompt_from_state(self):
        path = self.stage()
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                self.queue_receipt(),
            ]
            self.assertEqual(
                operations.enqueue_handoff(self.thread_id, self.turn_id)["status"],
                "queued",
            )
            queued_prompt = app.call.call_args_list[2].args[1]["input"][0]["text"]
            self.assertEqual(queued_prompt, self.prompt)
        state = HANDOFF_STATE.read_state(path)
        self.assertEqual(state["phase"], "queued")
        self.assertEqual(
            state["queued_prompt_digest"], HANDOFF_INPUT.prompt_digest(queued_prompt)
        )
        self.assertNotIn("prompt", state)
        with patch.object(operations, "AppServerReader") as reader:
            self.assertEqual(
                operations.enqueue_handoff(self.thread_id, self.turn_id),
                {"queued_submission_id": "queued-1", "status": "already_queued"},
            )
            reader.assert_not_called()

    def test_queue_preserves_all_native_input_and_text_spans(self):
        path = self.stage()
        content = [
            {
                "type": "text",
                "text": self.prompt,
                "text_elements": [
                    {"byteRange": {"start": 0, "end": 4}, "placeholder": "ref"}
                ],
            },
            {
                "type": "image",
                "url": "data:image/png;base64,aW1hZ2U=",
                "detail": "original",
            },
            {"type": "localImage", "path": "/tmp/screenshot.png"},
            {"type": "audio", "url": "data:audio/wav;base64,YXVkaW8="},
            {"type": "localAudio", "path": "/tmp/voice.wav"},
            {
                "type": "mention",
                "name": "screencast.mov",
                "path": "/tmp/screencast.mov",
            },
            {
                "type": "skill",
                "name": "model-fit",
                "path": "/tmp/skills/model-fit/SKILL.md",
            },
        ]
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(content),
                self.queue_receipt(content),
            ]
            operations.enqueue_handoff(self.thread_id, self.turn_id)
            queued = app.call.call_args_list[-1].args[1]["input"]
        self.assertEqual(queued[1:], content[1:])
        self.assertEqual(queued[0]["text_elements"], content[0]["text_elements"])
        self.assertEqual(content[0]["text"], self.prompt)
        self.assertEqual(queued[0]["text"], self.prompt)
        state = HANDOFF_STATE.read_state(path)
        self.assertEqual(
            state["source_input_digest"], HANDOFF_INPUT.input_digest(content)
        )
        self.assertEqual(
            state["queued_input_digest"], HANDOFF_INPUT.input_digest(queued)
        )
        self.assertNotIn("data:image", path.read_text())
        self.assertNotIn("screenshot.png", path.read_text())

    def test_native_local_images_are_accepted_and_canonical_digest_is_saved(self):
        path = self.stage()
        content = [{"type": "text", "text": self.prompt}] + [
            {"type": "localImage", "path": f"/tmp/image-{n}.jpeg", "detail": None}
            for n in range(5)
        ]
        native = [{"type": "text", "text": self.prompt}] + [
            {
                "type": "image",
                "url": f"data:image/jpeg;base64,aW1hZ2U{n}",
                "detail": None,
            }
            for n in range(5)
        ]
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(content),
                {"queuedSubmission": {"id": "queued-1", "input": native}},
            ]
            self.assertEqual(
                operations.enqueue_handoff(self.thread_id, self.turn_id)["status"],
                "queued",
            )
            self.assertNotIn(
                "thread/queue/delete",
                [call.args[0] for call in app.call.call_args_list],
            )
        state = HANDOFF_STATE.read_state(path)
        self.assertEqual(
            state["source_input_digest"], HANDOFF_INPUT.input_digest(content)
        )
        self.assertEqual(
            state["queued_input_digest"], HANDOFF_INPUT.input_digest(native)
        )
        self.assertNotIn("base64", path.read_text())

    def test_input_without_text_keeps_attachments_without_adding_text(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state["prompt"] = ""
        HANDOFF_STATE.write_state(path, state)
        content = [
            {"type": "image", "url": "data:image/png;base64,aW1hZ2U=", "detail": None}
        ]
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(content),
                self.queue_receipt(content),
            ]
            operations.enqueue_handoff(self.thread_id, self.turn_id)
            queued = app.call.call_args_list[-1].args[1]["input"]
        self.assertEqual(queued[0], content[0])
        self.assertEqual(queued, content)

    def test_missing_or_mismatched_source_never_queues_partial_input(self):
        for response in [
            {"data": [], "nextCursor": None},
            self.source_response([{"type": "text", "text": "Another instruction"}]),
        ]:
            with self.subTest(response=response):
                path = self.stage()
                with patch.object(operations, "AppServerReader") as reader:
                    app = reader.return_value.__enter__.return_value
                    app.call.side_effect = [
                        {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                        response,
                    ]
                    with self.assertRaisesRegex(ValueError, "Source user input"):
                        operations.enqueue_handoff(self.thread_id, self.turn_id)
                    self.assertNotIn(
                        "thread/queue/add", [c.args[0] for c in app.call.call_args_list]
                    )
                self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "ready")

    def test_incomplete_native_receipt_preserves_unknown_attempt_and_cannot_be_retried(
        self,
    ):
        receipts = (
            {"id": "queued-1", "input": []},
            {"id": "queued-1"},
            {"id": "queued-1", "input": {"invalid": True}},
            {"id": "queued-1", "input": [None]},
        )
        for receipt in receipts:
            with self.subTest(receipt=receipt):
                path = self.stage()
                content = [
                    {"type": "text", "text": self.prompt},
                    {"type": "image", "url": "image"},
                ]
                with patch.object(operations, "AppServerReader") as reader:
                    app = reader.return_value.__enter__.return_value
                    app.call.side_effect = [
                        {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                        self.source_response(content),
                        {"queuedSubmission": receipt},
                    ]
                    with self.assertRaisesRegex(
                        ValueError, "receipt input is unavailable"
                    ):
                        operations.enqueue_handoff(self.thread_id, self.turn_id)
                    self.assertNotIn(
                        "thread/queue/delete",
                        [c.args[0] for c in app.call.call_args_list],
                    )
                self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "attempting")
                self.assertEqual(
                    HANDOFF_STATE.read_state(path)["queued_submission_id"], "queued-1"
                )
                with self.assertRaisesRegex(RuntimeError, "do not retry"):
                    operations.enqueue_handoff(self.thread_id, self.turn_id)

    def test_incomplete_preparation_cannot_start_native_queue_io(self):
        for missing in ("target_effort", "created_at", "prompt"):
            with self.subTest(missing=missing):
                path = self.stage()
                state = HANDOFF_STATE.read_state(path)
                state.pop(missing)
                HANDOFF_STATE.write_state(path, state)
                before = path.read_bytes()
                with patch.object(operations, "AppServerReader") as reader:
                    with self.assertRaises(ValueError):
                        operations.enqueue_handoff(self.thread_id, self.turn_id)
                    reader.assert_not_called()
                self.assertEqual(path.read_bytes(), before)

    def test_uncertain_queue_attempt_is_not_retried(self):
        path = self.stage()
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                TimeoutError("unknown outcome"),
            ]
            with self.assertRaises(TimeoutError):
                operations.enqueue_handoff(self.thread_id, self.turn_id)
        state = HANDOFF_STATE.read_state(path)
        self.assertEqual(state["phase"], "attempting")
        self.assertNotIn("prompt", state)
        with patch.object(operations, "AppServerReader") as reader:
            with self.assertRaisesRegex(RuntimeError, "do not retry"):
                operations.enqueue_handoff(self.thread_id, self.turn_id)
            reader.assert_not_called()

    def test_explicit_queue_rejection_clears_handoff(self):
        path = self.stage()
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                CODEX_CONNECTION.AppServerRPCError(
                    "thread/queue/add: queue cannot contain more than 100 submissions"
                ),
            ]
            with self.assertRaises(QueueRejected):
                operations.enqueue_handoff(self.thread_id, self.turn_id)
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "rejected")
        guard_event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        self.assertEqual(
            operations.guard_tool(guard_event)["hookSpecificOutput"][
                "permissionDecision"
            ],
            "deny",
        )
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            operations.enqueue_handoff(self.thread_id, self.turn_id)
        self.assertEqual(evaluate_request(self.event)["decision"], "block")
        next_event = dict(self.event, turn_id="new-turn")
        with (
            patch.object(
                operations,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
        ):
            self.assertIsNone(evaluate_request(next_event))
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")

    def test_expired_handoff_cannot_queue_old_task(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state["created_at"] = 0
        HANDOFF_STATE.write_state(path, state)
        with patch.object(operations, "AppServerReader") as reader:
            with self.assertRaisesRegex(ValueError, "expired"):
                operations.enqueue_handoff(self.thread_id, self.turn_id)
            reader.assert_not_called()

    def test_other_thread_cannot_queue_handoff(self):
        self.stage()
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "another-thread"}):
            with self.assertRaisesRegex(ValueError, "target Desktop thread"):
                operations.enqueue_handoff(self.thread_id, self.turn_id)

    def test_queue_error_records_location_without_error_payload(self):
        error_output = io.StringIO()
        with (
            patch(
                "sys.argv",
                [
                    "desktop.py",
                    "queue",
                    "--thread-id",
                    self.thread_id,
                    "--turn-id",
                    self.turn_id,
                ],
            ),
            patch.object(
                QUEUE, "enqueue", side_effect=RuntimeError("private request text")
            ),
            redirect_stderr(error_output),
        ):
            self.assertEqual(QUEUE.queue_handoff("test-thread", "test-turn"), 1)
        audit = (self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl").read_text()
        failure = json.loads(audit.splitlines()[-1])
        self.assertEqual(failure["outcome"], "auto_queue_error:RuntimeError")
        self.assertEqual(failure["details"]["hook_event"], "queue")
        self.assertIn("failure_line", failure["details"])
        self.assertNotIn("private request text", audit + error_output.getvalue())
