"""Desktop replay scenarios."""

from unittest.mock import patch

from fixtures.autoswitch.assessment import evaluate_request
import vector_prime.entrypoints.hooks.instructions as HOOKS_INSTRUCTIONS
from vector_prime.entrypoints.hooks import operations
import vector_prime.application.submission.helpers.content as HANDOFF_INPUT
import vector_prime.infrastructure.adapters.filesystem.state as HANDOFF_STATE


from fixtures.autoswitch.desktop import DesktopHandoffCase


class ReplayTests(DesktopHandoffCase):
    def test_replay_admits_native_hook_prompt_without_inventing_text_separators(self):
        path = self.stage()
        source = [
            {"type": "text", "text": self.prompt},
            {"type": "image", "url": "data:image/png;base64,cmVk", "detail": "high"},
        ]
        correction = {
            "type": "text",
            "text": "Add correction: true",
            "text_elements": [],
        }
        self.prepare_ready(
            dict(self.event, turn_id="correction-turn", prompt=correction["text"])
        )
        queued = [source[0], source[1], dict(correction, text=correction["text"])]
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(source),
                self.source_response([correction]),
                {"queuedSubmission": {"id": "queued-1", "input": queued}},
            ]
            operations.enqueue_handoff(self.thread_id, self.turn_id)
        native_prompt = self.prompt + "Add correction: true"
        with (
            patch.object(
                operations,
                "session_input",
                return_value={
                    "active_profile": {
                        "model": "gpt-6-sol",
                        "effort": "medium",
                        "speed": None,
                    }
                },
            ),
            patch.object(operations, "AppServerReader") as reader,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                {
                    "data": [
                        {
                            "item": {
                                "id": "native-message",
                                "clientId": self.turn_id,
                                "type": "userMessage",
                                "content": queued,
                            }
                        }
                    ],
                    "nextCursor": None,
                },
                {"data": [], "nextCursor": None},
            ]
            operations.submit_prompt(
                dict(self.event, turn_id="replay-turn", prompt=native_prompt)
            )
            result = operations.assess_submitted()
        self.assertEqual(
            result["hookSpecificOutput"]["additionalContext"],
            HOOKS_INSTRUCTIONS.REPLAY_CONTEXT,
        )
        self.assertEqual(
            HANDOFF_STATE.read_state(path)["replay_turn_id"], "replay-turn"
        )

    def test_new_request_cancels_old_queued_request(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.pop("prompt")
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
        HANDOFF_STATE.write_state(path, state)
        new_event = dict(self.event, prompt="Show the backlog", turn_id="new-turn")
        with (
            patch.object(
                operations,
                "session_input",
                return_value={
                    "task": "Show the backlog",
                    "active_profile": self.active,
                },
            ),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
            patch.object(operations, "AppServerReader") as reader,
        ):
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"data": [{"id": "queued-1"}], "nextCursor": None},
                {"deleted": True},
            ]
            self.assertIsNone(evaluate_request(new_event))
            self.assertEqual(app.call.call_args_list[1].args[0], "thread/queue/delete")
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")

    def test_new_request_waits_after_old_item_leaves_queue(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.pop("prompt")
        state.update(
            phase="queued",
            queued_submission_id="queued-1",
            queued_at=100,
            replay_turn_id="replay-turn",
        )
        HANDOFF_STATE.write_state(path, state)
        new_event = dict(self.event, prompt="Show the backlog", turn_id="new-turn")
        with patch.object(operations, "AppServerReader") as reader:
            reader.return_value.__enter__.return_value.call.side_effect = [
                {"data": [], "nextCursor": None},
                {
                    "data": [
                        {
                            "id": "replay-turn",
                            "startedAt": 101,
                            "status": "inProgress",
                            "completedAt": None,
                        }
                    ],
                    "nextCursor": None,
                },
            ]
            self.assertEqual(evaluate_request(new_event)["decision"], "block")
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "queued")

    def test_completed_replay_releases_new_request(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.pop("prompt")
        state.update(
            phase="queued",
            queued_submission_id="queued-1",
            created_at=100,
            queued_at=100,
        )
        HANDOFF_STATE.write_state(path, state)
        new_event = dict(self.event, prompt="Show the backlog", turn_id="new-turn")
        with (
            patch.object(
                operations,
                "session_input",
                return_value={
                    "task": "Show the backlog",
                    "active_profile": self.active,
                },
            ),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
            patch.object(operations, "AppServerReader") as reader,
        ):
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"data": [], "nextCursor": None},
                {
                    "data": [
                        {
                            "id": "replay-turn",
                            "startedAt": 101,
                            "completedAt": 102,
                            "status": "completed",
                        }
                    ],
                    "nextCursor": None,
                },
                {
                    "data": [
                        {
                            "item": {
                                "type": "userMessage",
                                "content": [{"type": "text", "text": self.prompt}],
                            }
                        }
                    ],
                    "nextCursor": None,
                },
            ]
            state["queued_prompt_digest"] = HANDOFF_INPUT.prompt_digest(self.prompt)
            HANDOFF_STATE.write_state(path, state)
            self.assertIsNone(evaluate_request(new_event))
            self.assertEqual(
                [call.args[0] for call in app.call.call_args_list],
                ["thread/queue/list", "thread/turns/list", "thread/items/list"],
            )
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")

    def test_completed_source_and_missing_replay_releases_new_work(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.update(
            phase="queued",
            queued_submission_id="gone",
            queued_at=100,
            queued_prompt_digest=HANDOFF_INPUT.prompt_digest("queued request"),
        )
        HANDOFF_STATE.write_state(path, state)
        with (
            patch.object(
                operations,
                "session_input",
                return_value={"task": "new work", "active_profile": self.active},
            ),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
            patch.object(operations, "AppServerReader") as reader,
        ):
            app = reader.return_value.__enter__.return_value
            source = {"id": self.turn_id, "startedAt": 99, "status": "completed"}
            app.call.side_effect = [
                {"data": [], "nextCursor": None},
                {"data": [source], "nextCursor": None},
                {
                    "data": [{"id": "new-turn", "status": "inProgress"}],
                    "nextCursor": "older",
                },
                {"data": [source], "nextCursor": None},
            ]
            self.assertIsNone(
                evaluate_request(
                    dict(self.event, turn_id="new-turn", prompt="new work")
                )
            )
            self.assertFalse(
                any((c.args[0] == "thread/queue/add" for c in app.call.call_args_list))
            )
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")

    def test_interrupted_source_with_removed_queue_item_releases_new_request(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.pop("prompt")
        state.update(
            phase="queued",
            queued_submission_id="queued-1",
            queued_at=100,
            queued_prompt_digest=HANDOFF_INPUT.prompt_digest(
                self.prompt + "\n\n<!-- model-fit-replay:retained -->"
            ),
        )
        HANDOFF_STATE.write_state(path, state)
        new_event = dict(self.event, turn_id="new-turn")
        with (
            patch.object(
                operations,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
            patch.object(operations, "AppServerReader") as reader,
        ):
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"data": [], "nextCursor": None},
                {
                    "data": [
                        {
                            "id": self.turn_id,
                            "startedAt": 99,
                            "status": "interrupted",
                            "completedAt": None,
                        }
                    ],
                    "nextCursor": None,
                },
                {
                    "data": [{"id": self.turn_id, "status": "interrupted"}],
                    "nextCursor": None,
                },
            ]
            self.assertIsNone(evaluate_request(new_event))
            self.assertEqual(
                [call.args[0] for call in app.call.call_args_list],
                ["thread/queue/list", "thread/turns/list", "thread/turns/list"],
            )
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")

    def test_same_text_after_dequeue_does_not_admit_manual_resubmission(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.pop("prompt")
        state.update(
            phase="queued",
            queued_submission_id="queued-1",
            queued_at=100,
            replay_turn_id="replay-turn",
            queued_prompt_digest=HANDOFF_INPUT.prompt_digest(self.prompt),
        )
        HANDOFF_STATE.write_state(path, state)
        with patch.object(operations, "AppServerReader") as reader:
            reader.return_value.__enter__.return_value.call.side_effect = [
                {"data": [], "nextCursor": None},
                {
                    "data": [
                        {
                            "id": "replay-turn",
                            "startedAt": 101,
                            "status": "inProgress",
                            "completedAt": None,
                        }
                    ],
                    "nextCursor": None,
                },
            ]
            self.assertEqual(
                evaluate_request(dict(self.event, turn_id="manual-turn"))["decision"],
                "block",
            )
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "queued")

    def test_terminal_replay_releases_new_request_without_completion_timestamp(self):
        for status in ("interrupted", "failed"):
            with self.subTest(status=status):
                path = self.stage()
                state = HANDOFF_STATE.read_state(path)
                state.pop("prompt")
                state.update(
                    phase="queued",
                    queued_submission_id="queued-1",
                    queued_at=100,
                    replay_turn_id="replay-turn",
                    queued_prompt_digest=HANDOFF_INPUT.prompt_digest(self.prompt),
                )
                HANDOFF_STATE.write_state(path, state)
                new_event = dict(
                    self.event, prompt="Show the backlog", turn_id="new-turn"
                )
                with (
                    patch.object(
                        operations,
                        "session_input",
                        return_value={
                            "task": "Show the backlog",
                            "active_profile": self.active,
                        },
                    ),
                    patch.object(
                        operations, "triage", return_value={"decision": "keep"}
                    ),
                    patch.object(operations, "AppServerReader") as reader,
                ):
                    app = reader.return_value.__enter__.return_value
                    app.call.side_effect = [
                        {"data": [], "nextCursor": None},
                        {
                            "data": [
                                {
                                    "id": "replay-turn",
                                    "startedAt": 101,
                                    "status": status,
                                    "completedAt": None,
                                }
                            ],
                            "nextCursor": None,
                        },
                    ]
                    self.assertIsNone(evaluate_request(new_event))
                self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")

    def test_consumed_replay_denies_repeated_transfer_without_changing_state(self):
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
        replay = dict(
            self.event, turn_id="replay-turn", prompt=self.prompt, model="gpt-6-sol"
        )
        with (
            patch.object(operations, "AppServerReader") as reader,
            patch.object(
                operations,
                "session_input",
                return_value={
                    "active_profile": {
                        "model": "gpt-6-sol",
                        "effort": "medium",
                        "speed": None,
                    }
                },
            ),
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                {
                    "data": [
                        {
                            "item": {
                                "id": "native-message",
                                "clientId": self.turn_id,
                                "type": "userMessage",
                                "content": [{"type": "text", "text": self.prompt}],
                            }
                        }
                    ],
                    "nextCursor": None,
                },
                {"data": [], "nextCursor": None},
            ]
            operations.submit_prompt(replay)
            output = operations.assess_submitted()
        self.assertEqual(
            output["hookSpecificOutput"]["additionalContext"],
            HOOKS_INSTRUCTIONS.REPLAY_CONTEXT,
        )
        saved = path.read_bytes()
        tools = [
            (
                "mcp__codex_app__send_message_to_thread",
                {
                    "threadId": self.thread_id,
                    "model": "gpt-6-luna",
                    "thinking": "low",
                    "prompt": HOOKS_INSTRUCTIONS.CONTROL_PROMPT,
                },
            ),
            (
                "Bash",
                {
                    "command": HOOKS_INSTRUCTIONS.queue_command(
                        self.thread_id, "unrelated-turn"
                    )
                },
            ),
            (
                "mcp__codex_app__send_message_to_thread",
                {
                    "threadId": "another-thread",
                    "prompt": HOOKS_INSTRUCTIONS.CONTROL_PROMPT,
                },
            ),
            (
                "mcp__codex_app__send_message_to_thread",
                {
                    "threadId": "current",
                    "model": "gpt-6-sol",
                    "thinking": "medium",
                    "prompt": HOOKS_INSTRUCTIONS.CONTROL_PROMPT,
                },
            ),
            (
                "Bash",
                {"command": HOOKS_INSTRUCTIONS.queue_command("current", "source")},
            ),
        ]
        for tool, arguments in tools:
            for contended in (False, True):
                with self.subTest(tool=tool, contended=contended):
                    event = dict(replay, tool_name=tool, tool_input=arguments)
                    if contended:
                        with patch.object(
                            HANDOFF_STATE, "locked_state", side_effect=BlockingIOError
                        ):
                            denied = operations.guard_tool(event)
                    else:
                        denied = operations.guard_tool(event)
                    self.assertEqual(
                        denied["hookSpecificOutput"]["permissionDecision"], "deny"
                    )
                    self.assertIn(
                        "perform the original user request",
                        denied["hookSpecificOutput"][
                            "permissionDecisionReason"
                        ].casefold(),
                    )
                    self.assertEqual(path.read_bytes(), saved)
        ordinary = [
            ("Bash", {"command": "git status --short"}),
            (
                "mcp__codex_app__send_message_to_thread",
                {"threadId": "another-thread", "prompt": "Continue the assigned task"},
            ),
            (
                "mcp__codex_app__send_message_to_thread",
                {"threadId": self.thread_id, "prompt": "User clarification"},
            ),
        ]
        for tool, arguments in ordinary:
            self.assertIsNone(
                operations.guard_tool(
                    dict(replay, tool_name=tool, tool_input=arguments)
                )
            )
        self.assertEqual(path.read_bytes(), saved)
