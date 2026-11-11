"""Desktop hook assessment scenarios."""

import io
import json
import os
import subprocess
import sys

from contextlib import redirect_stdout
from unittest.mock import patch

from fixtures.autoswitch.assessment import evaluate_request
import vector_prime.entrypoints.hooks.instructions as HOOKS_INSTRUCTIONS
import vector_prime.entrypoints.hooks.native_contract as DESKTOP_CONFIGURATION
from vector_prime.entrypoints.hooks import operations
import vector_prime.application.submission.helpers.content as HANDOFF_INPUT
import vector_prime.infrastructure.adapters.filesystem.state as HANDOFF_STATE
import vector_prime.entrypoints.hooks.events.dispatch as EVENTS


from fixtures.autoswitch.desktop import DesktopHandoffCase


class HookAssessmentTests(DesktopHandoffCase):
    def test_assessment_dependencies_admit_work_without_starting_native_clients(self):
        request = {"task": self.prompt, "active_profile": self.active}
        with (
            patch.object(
                operations,
                "session_input",
                side_effect=AssertionError("native context lookup"),
            ),
            patch.object(
                operations,
                "triage",
                side_effect=AssertionError("native inference"),
            ),
        ):
            self.assertIsNone(
                evaluate_request(
                    self.event,
                    context_reader=lambda event: request,
                    assessor=lambda request: {"decision": "keep"},
                )
            )
        self.assertEqual(
            HANDOFF_STATE.read_state(HANDOFF_STATE.state_path(self.thread_id))["phase"],
            "passed",
        )
        self.assertIsNone(
            operations.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )

    def test_assessment_audit_preserves_decision_and_hashes_without_private_context(
        self,
    ):
        request = {
            "task": self.prompt,
            "active_profile": self.active,
            "context": "private plan for a running service",
        }
        with (
            patch.object(operations, "session_input", return_value=request),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
        ):
            self.assertIsNone(evaluate_request(self.event))
        raw = (self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl").read_text()
        row = next(
            (
                json.loads(line)
                for line in raw.splitlines()
                if json.loads(line)["outcome"] == "auto_assessed"
            )
        )
        self.assertEqual(row["details"]["triage_decision"], "keep")
        self.assertEqual(row["details"]["active_model"], "gpt-6-luna")
        self.assertEqual(
            row["details"]["context_sha256"],
            HANDOFF_INPUT.prompt_digest(request["context"]),
        )
        self.assertNotIn(request["context"], raw)
        self.assertNotIn(self.prompt, raw)

    def test_recommendation_stages_exact_prompt_for_control_only_turn(self):
        request = {"task": self.prompt, "active_profile": self.active}
        with (
            patch.object(operations, "session_input", return_value=request),
            patch.object(operations, "triage", return_value=self.recommendation),
            patch.object(operations, "AppServerReader") as reader,
        ):
            reader.return_value.__enter__.return_value.call.return_value = {
                "data": [],
                "nextCursor": None,
            }
            result = evaluate_request(self.event)
        instruction = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("model=gpt-6-sol, thinking=medium", instruction)
        self.assertIn("queue --thread-id current --turn-id source", instruction)
        self.assertNotIn(self.thread_id, instruction)
        self.assertNotIn(self.turn_id, instruction)
        self.assertIn("do not perform the original task", instruction.casefold())
        state = HANDOFF_STATE.read_state(HANDOFF_STATE.state_path(self.thread_id))
        self.assertEqual(state["prompt"], self.prompt)
        self.assertEqual(state["source_turn_id"], self.turn_id)
        self.assertEqual(
            HANDOFF_STATE.state_path(self.thread_id).stat().st_mode & 511, 384
        )

    def test_keep_never_stages_or_switches(self):
        request = {"task": self.prompt, "active_profile": self.active}
        with (
            patch.object(operations, "session_input", return_value=request),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
            patch.object(operations, "AppServerReader") as reader,
        ):
            self.assertIsNone(evaluate_request(self.event))
            reader.assert_not_called()
        self.assertEqual(
            HANDOFF_STATE.read_state(HANDOFF_STATE.state_path(self.thread_id))["phase"],
            "passed",
        )

    def test_next_turn_after_keep_runs_triage_again(self):
        with (
            patch.object(
                operations,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
        ):
            self.assertIsNone(evaluate_request(self.event))
        with (
            patch.object(
                operations,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(
                operations, "triage", return_value=self.recommendation
            ) as triage,
            patch.object(operations, "AppServerReader") as reader,
        ):
            reader.return_value.__enter__.return_value.call.return_value = {
                "data": [],
                "nextCursor": None,
            }
            result = evaluate_request(dict(self.event, turn_id="next-turn"))
            triage.assert_called_once()
        self.assertIn("hookSpecificOutput", result)
        self.assertEqual(
            HANDOFF_STATE.read_state(HANDOFF_STATE.state_path(self.thread_id))["phase"],
            "ready",
        )

    def test_submission_registration_failure_blocks_unregistered_work(self):
        output = io.StringIO()
        with (
            patch.dict(
                os.environ, {DESKTOP_CONFIGURATION.AUTO_THREAD_ENV: self.thread_id}
            ),
            patch("sys.argv", ["desktop.py"]),
            patch("sys.stdin", io.StringIO(json.dumps(self.event))),
            patch.object(
                EVENTS,
                "submit_prompt",
                side_effect=subprocess.TimeoutExpired("triage", 45),
            ),
            patch.object(EVENTS, "record_audit") as audit,
            redirect_stdout(output),
        ):
            self.assertEqual(EVENTS.handle_event(), 0)
        self.assertEqual(json.loads(output.getvalue())["decision"], "block")
        self.assertIn("TimeoutExpired", audit.call_args_list[-1].args[2])

    def test_native_queue_admission_survives_long_wait_before_tool(self):
        for identifiers in [
            (self.thread_id, self.turn_id),
            ("wrong-thread", "wrong-turn"),
        ]:
            with self.subTest(identifiers=identifiers):
                path = self.stage()
                state = HANDOFF_STATE.read_state(path)
                state["created_at"] = 0
                HANDOFF_STATE.write_state(path, state)
                event = {
                    **self.event,
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": HOOKS_INSTRUCTIONS.queue_command(*identifiers)
                    },
                }
                with patch.object(operations.time, "time", return_value=4000):
                    result = operations.guard_tool(event)
                if result is not None:
                    self.assertEqual(
                        result["hookSpecificOutput"]["permissionDecision"], "allow"
                    )
                self.assertEqual(HANDOFF_STATE.read_state(path)["created_at"], 0)
                with (
                    patch.object(operations.time, "time", return_value=4001),
                    patch.object(operations, "AppServerReader") as reader,
                ):
                    app = reader.return_value.__enter__.return_value
                    app.call.side_effect = [
                        {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                        self.source_response(),
                        self.queue_receipt(),
                    ]
                    self.assertEqual(
                        operations.enqueue_handoff(self.thread_id, self.turn_id)[
                            "status"
                        ],
                        "queued",
                    )
                    self.assertEqual(
                        app.call.call_args_list[-1].args[1]["input"],
                        [{"type": "text", "text": self.prompt}],
                    )
                    self.assertEqual(
                        operations.enqueue_handoff(self.thread_id, self.turn_id)[
                            "status"
                        ],
                        "already_queued",
                    )

    def test_foreign_or_ordinary_tool_does_not_renew_expired_transfer(self):
        for turn, command in [
            (
                "other-turn",
                HOOKS_INSTRUCTIONS.queue_command(self.thread_id, self.turn_id),
            ),
            (self.turn_id, "pwd"),
        ]:
            with self.subTest(turn=turn, command=command):
                path = self.stage()
                state = HANDOFF_STATE.read_state(path)
                state["created_at"] = 0
                HANDOFF_STATE.write_state(path, state)
                before = path.read_bytes()
                result = operations.guard_tool(
                    {
                        **self.event,
                        "turn_id": turn,
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    }
                )
                self.assertEqual(
                    result["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                self.assertEqual(path.read_bytes(), before)
                with self.assertRaisesRegex(ValueError, "expired"):
                    operations.enqueue_handoff(self.thread_id, self.turn_id)

    def test_prompt_dispatch_defers_assessment_without_false_handoff_audit(self):
        event = dict(self.event, turn_id="replay-turn")
        output = io.StringIO()
        with (
            patch.dict(
                os.environ, {DESKTOP_CONFIGURATION.AUTO_THREAD_ENV: self.thread_id}
            ),
            patch("sys.stdin", io.StringIO(json.dumps(event))),
            patch.object(sys, "argv", ["desktop.py"]),
            patch.object(
                operations,
                "session_input",
                side_effect=AssertionError("Premature native read"),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(EVENTS.handle_event(), 0)
        self.assertEqual(
            json.loads(output.getvalue())["hookSpecificOutput"]["additionalContext"],
            HOOKS_INSTRUCTIONS.pending_context()["hookSpecificOutput"][
                "additionalContext"
            ],
        )
        audit = (
            (self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        outcomes = [json.loads(line)["outcome"] for line in audit]
        self.assertEqual(outcomes.count("auto_started"), 1)
        self.assertEqual(outcomes.count("auto_deferred"), 1)
        self.assertLess(outcomes.index("auto_started"), outcomes.index("auto_deferred"))
        self.assertNotIn("auto_handoff", outcomes)

    def test_malformed_hook_event_is_audited_without_payload(self):
        output = io.StringIO()
        with (
            patch.dict(
                os.environ, {DESKTOP_CONFIGURATION.AUTO_THREAD_ENV: self.thread_id}
            ),
            patch("sys.argv", ["desktop.py"]),
            patch("sys.stdin", io.StringIO('["private request text"]')),
            redirect_stdout(output),
        ):
            self.assertEqual(EVENTS.handle_event(), 0)
        self.assertEqual(output.getvalue(), "")
        audit = (self.home / ".tmp/model-fit-hook-audit/test-thread.jsonl").read_text()
        self.assertEqual(json.loads(audit)["outcome"], "auto_error:ValueError")
        self.assertNotIn("private request text", audit)
