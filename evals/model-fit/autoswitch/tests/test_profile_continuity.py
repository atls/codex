"""Desktop profile continuity scenarios."""

from unittest.mock import patch

from fixtures.autoswitch.assessment import evaluate_request
import vector_prime.entrypoints.hooks.instructions as HOOKS_INSTRUCTIONS
from vector_prime.entrypoints.hooks import operations
import vector_prime.infrastructure.adapters.filesystem.state as HANDOFF_STATE


from fixtures.autoswitch.desktop import DesktopHandoffCase


class ProfileContinuityTests(DesktopHandoffCase):
    def test_ready_handoff_keeps_original_and_same_turn_correction(self):
        self.stage()
        correction = {
            "type": "text",
            "text": "Preserve the connection to the original task",
            "text_elements": [],
        }
        source = {"type": "text", "text": self.prompt, "text_elements": []}
        content = [source, correction]
        response = {
            "data": [
                {"item": {"type": "userMessage", "content": [value]}}
                for value in content
            ],
            "nextCursor": None,
        }
        self.prepare_ready(dict(self.event, prompt=correction["text"]))
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                response,
                self.queue_receipt(content),
            ]
            self.assertEqual(
                operations.enqueue_handoff(self.thread_id, self.turn_id)["status"],
                "queued",
            )
            queued = app.call.call_args_list[-1].args[1]["input"]
        self.assertEqual(queued[0], source)
        self.assertEqual(queued[1]["text_elements"], [])
        self.assertEqual(queued[1]["text"], correction["text"])

    def test_next_turn_reassesses_ready_handoff_without_replacing_source(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state["created_at"] = 0
        HANDOFF_STATE.write_state(path, state)
        event = dict(self.event, turn_id="next-turn", prompt="And retain the link")
        result = self.prepare_ready(event)
        self.assertIn(
            HOOKS_INSTRUCTIONS.queue_command("current", "source"),
            result["hookSpecificOutput"]["additionalContext"],
        )
        self.assertEqual(HANDOFF_STATE.read_state(path)["source_turn_id"], self.turn_id)
        self.assertGreater(HANDOFF_STATE.read_state(path)["created_at"], 0)
        self.assertEqual(
            operations.guard_tool(
                {
                    "session_id": self.thread_id,
                    "turn_id": "next-turn",
                    "tool_name": "Bash",
                    "tool_input": {"command": "touch forbidden"},
                }
            )["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        content = [
            {"type": "text", "text": self.prompt},
            {"type": "text", "text": event["prompt"]},
        ]
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                self.source_response([content[1]]),
                self.queue_receipt(content),
            ]
            self.assertEqual(
                operations.enqueue_handoff(self.thread_id, self.turn_id)["status"],
                "queued",
            )
            self.assertEqual(
                app.call.call_args_list[-1].args[1]["input"][0], content[0]
            )

    def test_same_text_in_new_turn_replaces_pending_native_message(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
        HANDOFF_STATE.write_state(path, state)
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
                {"data": [{"id": "queued-1"}], "nextCursor": None},
                {"deleted": True},
            ]
            self.assertIsNone(evaluate_request(dict(self.event, turn_id="new-turn")))
            self.assertEqual(
                [c.args[0] for c in app.call.call_args_list],
                ["thread/queue/list", "thread/queue/delete"],
            )
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")

    def test_user_keeps_current_profile_during_pending_handoff(self):
        for turn_id in (self.turn_id, "new-user-turn"):
            with self.subTest(turn_id=turn_id):
                self.stage()
                event = dict(
                    self.event,
                    turn_id=turn_id,
                    prompt="Do not switch models; continue on the current profile and finish the task",
                )
                request = {"task": event["prompt"], "active_profile": self.active}
                with (
                    patch.object(operations, "session_input", return_value=request),
                    patch.object(
                        operations, "triage", return_value={"decision": "keep"}
                    ) as triage,
                    patch.object(operations, "AppServerReader") as reader,
                ):
                    output = evaluate_request(event)
                    reader.assert_not_called()
                triage.assert_called_once()
                self.assertEqual(triage.call_args.args[0]["task"], event["prompt"])
                self.assertIn(self.prompt, triage.call_args.args[0]["context"])
                self.assertEqual(
                    output["hookSpecificOutput"]["additionalContext"],
                    HOOKS_INSTRUCTIONS.HANDOFF_CANCELLED_CONTEXT,
                )
                self.assertEqual(
                    HANDOFF_STATE.read_state(HANDOFF_STATE.state_path(self.thread_id)),
                    {
                        "phase": "passed",
                        "source_turn_id": turn_id,
                        "profile_context_turn_id": turn_id,
                        "assessment_decision": "keep",
                    },
                )
                self.assertIsNone(
                    operations.guard_tool(
                        {
                            "session_id": self.thread_id,
                            "turn_id": turn_id,
                            "tool_name": "Bash",
                            "tool_input": {"command": "echo continue"},
                        }
                    )
                )

    def test_unknown_reassessment_releases_unqueued_handoff_and_allows_task(self):
        path = self.stage()
        event = dict(
            self.event, turn_id="new-user-turn", prompt="Continue the original task"
        )
        request = {"task": event["prompt"], "active_profile": self.active}
        with (
            patch.object(operations, "session_input", return_value=request),
            patch.object(
                operations, "triage", return_value={"decision": "unknown"}
            ) as triage,
        ):
            output = evaluate_request(event)
        triage.assert_called_once()
        self.assertNotEqual(output.get("decision"), "block")
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")
        self.assertIsNone(
            operations.guard_tool(
                {**event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )
        audit = (self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl").read_text()
        self.assertIn("pending_reassessed_unknown", audit)
        self.assertIn("auto_handoff_cancelled", audit)

    def test_profile_choice_survives_input_and_native_history_failures(self):
        path = HANDOFF_STATE.state_path(self.thread_id)
        choice = "Do not switch models; continue on the current profile"
        prior = {
            "phase": "passed",
            "source_turn_id": "choice-turn",
            "profile_context_turn_id": "choice-turn",
        }
        event = dict(
            self.event, turn_id="follow-up-turn", prompt="Continue the same task"
        )
        request = {"task": event["prompt"], "active_profile": self.active}
        path.parent.mkdir(parents=True, exist_ok=True)
        HANDOFF_STATE.write_state(path, prior)
        with (
            patch.object(
                operations,
                "session_input",
                side_effect=RuntimeError("temporary input read failure"),
            ),
            self.assertRaises(RuntimeError),
        ):
            evaluate_request(event)
        self.assertEqual(HANDOFF_STATE.read_state(path), prior)
        with (
            patch.object(operations, "session_input", return_value=request),
            patch.object(operations, "AppServerReader") as reader,
            self.assertRaises(TimeoutError),
        ):
            reader.return_value.__enter__.return_value.call.side_effect = TimeoutError(
                "temporary history read failure"
            )
            evaluate_request(event)
        self.assertEqual(HANDOFF_STATE.read_state(path), prior)
        with (
            patch.object(operations, "session_input", return_value=request),
            patch.object(operations, "AppServerReader") as reader,
            patch.object(
                operations, "triage", return_value={"decision": "keep"}
            ) as triage,
        ):
            reader.return_value.__enter__.return_value.call.return_value = (
                self.source_response([{"type": "text", "text": choice}])
            )
            evaluate_request(event)
        self.assertIn(choice, triage.call_args.args[0]["context"])
        self.assertEqual(
            HANDOFF_STATE.read_state(path),
            {
                "phase": "passed",
                "source_turn_id": event["turn_id"],
                "profile_context_turn_id": "choice-turn",
                "assessment_decision": "keep",
            },
        )

    def test_cancelled_handoff_keeps_native_user_context_beyond_recent_turns(self):
        path = self.stage()
        choice = "Do not switch models; continue on the current profile"
        choice_turn = "user-choice-turn"
        event = dict(self.event, turn_id=choice_turn, prompt=choice)
        with (
            patch.object(
                operations,
                "session_input",
                return_value={"task": choice, "active_profile": self.active},
            ),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
        ):
            evaluate_request(event)
        for index in range(4):
            next_turn = "continuation-" + str(index)
            request = {
                "task": "Continue the same task",
                "active_profile": self.active,
                "context": "Recent messages no longer include the profile choice",
            }
            with (
                patch.object(operations, "session_input", return_value=request),
                patch.object(
                    operations, "triage", return_value={"decision": "keep"}
                ) as triage,
                patch.object(operations, "AppServerReader") as reader,
            ):
                reader.return_value.__enter__.return_value.call.return_value = (
                    self.source_response([{"type": "text", "text": choice}])
                )
                self.assertIsNone(
                    evaluate_request(
                        dict(self.event, turn_id=next_turn, prompt=request["task"])
                    )
                )
                call = reader.return_value.__enter__.return_value.call.call_args
                self.assertEqual(call.args[1]["turnId"], choice_turn)
                self.assertIn(choice, triage.call_args.args[0]["context"])
            self.assertEqual(
                HANDOFF_STATE.read_state(path)["profile_context_turn_id"], choice_turn
            )
            self.assertEqual(
                HANDOFF_STATE.read_state(path)["source_turn_id"], next_turn
            )

    def test_pending_reassessment_does_not_overwrite_queue_transition(self):
        path = self.stage()
        event = dict(
            self.event, turn_id="new-user-turn", prompt="Continue on the current model"
        )

        def concurrent_queue(request):
            state = HANDOFF_STATE.read_state(path)
            state["phase"] = "queued"
            state["queued_submission_id"] = "concurrent-queue"
            HANDOFF_STATE.write_state(path, state)
            return {"decision": "keep"}

        with (
            patch.object(
                operations,
                "session_input",
                return_value={"task": event["prompt"], "active_profile": self.active},
            ),
            patch.object(operations, "triage", side_effect=concurrent_queue),
        ):
            output = evaluate_request(event)
        self.assertEqual(output["decision"], "block")
        self.assertEqual(
            HANDOFF_STATE.read_state(path)["queued_submission_id"], "concurrent-queue"
        )
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "queued")
