"""Contract checks for the opt-in Desktop queued handoff."""

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[4]
from vector_prime.application.handoff.types.progress import TransferInputEvidence
from vector_prime.application.handoff.types.replay import BoundReplay, UnboundReplay
from fixtures.autoswitch.assessment import evaluate_request
from fixtures.autoswitch.lock import held_lock
import vector_prime.entrypoints.hooks.instructions as HOOKS_INSTRUCTIONS
import vector_prime.entrypoints.hooks.native_contract as DESKTOP_CONFIGURATION
import vector_prime.entrypoints.hooks.operations as HANDOFF_GUARDS
import vector_prime.entrypoints.hooks.operations as HANDOFF_PREPARATION
import vector_prime.entrypoints.hooks.operations as HANDOFF_QUEUE
import vector_prime.application.submission.helpers.content as HANDOFF_INPUT
import vector_prime.infrastructure.adapters.codex.history as HANDOFF_CODEX
import vector_prime.infrastructure.adapters.codex.transport.connection as CODEX_CONNECTION
import vector_prime.infrastructure.adapters.filesystem.state as HANDOFF_STATE
import vector_prime.entrypoints.hooks.events.dispatch as EVENTS
import vector_prime.entrypoints.hooks.handlers.queue as QUEUE


class DesktopAutoSwitchTests(unittest.TestCase):
    thread_id = "test-thread"
    turn_id = "test-turn"
    prompt = "Design a snapshot search engine"
    active = {"model": "gpt-6-luna", "effort": "low", "speed": None}
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": thread_id,
        "turn_id": turn_id,
        "cwd": "/tmp",
        "model": "gpt-6-luna",
        "prompt": prompt,
    }
    recommendation = {
        "decision": "recommend_stronger",
        "active_model": "gpt-6-luna",
        "active_effort": "low",
        "active_speed": None,
        "recommended_model": "gpt-6-sol",
        "recommended_effort": "medium",
        "recommended_speed": None,
        "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
        "official_guidance": "Select the profile for the task.",
        "task_inference": "Design is needed.",
        "reason": "Deeper reasoning is needed.",
    }

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {"CODEX_HOME": self.temporary.name, "CODEX_THREAD_ID": self.thread_id},
        )
        self.environment.start()

    def test_assessment_dependencies_admit_work_without_starting_native_clients(self):
        request = {"task": self.prompt, "active_profile": self.active}
        with (
            patch.object(
                HANDOFF_PREPARATION,
                "session_input",
                side_effect=AssertionError("native context lookup"),
            ),
            patch.object(
                HANDOFF_PREPARATION,
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
            HANDOFF_GUARDS.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )

    def test_admitted_prompt_receives_completed_assessment_context(self):
        request = {"task": self.prompt, "active_profile": self.active}
        output = HANDOFF_PREPARATION.submit_prompt(
            self.event,
            context_reader=lambda event: request,
            assessor=lambda request: {"decision": "keep"},
        )
        self.assertEqual(output, HOOKS_INSTRUCTIONS.pending_context())
        reader = MagicMock()
        reader.__enter__.return_value.call.return_value = {
            "data": [
                {
                    "item": {
                        "type": "userMessage",
                        "id": "native-message",
                        "content": [{"type": "text", "text": self.prompt}],
                    }
                }
            ],
            "nextCursor": None,
        }
        reader.__enter__.return_value.call.side_effect = (
            lambda method, params, timeout: (
                {
                    "thread": {
                        "model": self.active["model"],
                        "reasoningEffort": self.active["effort"],
                    }
                }
                if method == "thread/read"
                else reader.__enter__.return_value.call.return_value
            )
        )
        output = HANDOFF_PREPARATION.assess_submitted(
            context_reader=lambda event: request,
            assessor=lambda request: {"decision": "keep"},
            native_factory=lambda cwd: reader,
        )
        self.assertIn(
            "already assessed",
            output["hookSpecificOutput"]["additionalContext"].casefold(),
        )
        self.assertIsNone(
            HANDOFF_GUARDS.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )

    def test_unknown_admission_is_not_reported_as_completed_assessment(self):
        request = {"task": self.prompt, "active_profile": self.active}
        output = HANDOFF_PREPARATION.submit_prompt(
            self.event,
            context_reader=lambda event: request,
            assessor=lambda request: {"decision": "unknown"},
        )
        self.assertEqual(output, HOOKS_INSTRUCTIONS.pending_context())
        reader = MagicMock()
        reader.__enter__.return_value.call.return_value = {
            "data": [
                {
                    "item": {
                        "type": "userMessage",
                        "id": "native-message",
                        "content": [{"type": "text", "text": self.prompt}],
                    }
                }
            ],
            "nextCursor": None,
        }
        reader.__enter__.return_value.call.side_effect = (
            lambda method, params, timeout: (
                {
                    "thread": {
                        "model": self.active["model"],
                        "reasoningEffort": self.active["effort"],
                    }
                }
                if method == "thread/read"
                else reader.__enter__.return_value.call.return_value
            )
        )
        output = HANDOFF_PREPARATION.assess_submitted(
            context_reader=lambda event: request,
            assessor=lambda request: {"decision": "unknown"},
            native_factory=lambda cwd: reader,
        )
        self.assertNotIn("hookSpecificOutput", output)
        self.assertIn("systemMessage", output)
        self.assertIn("continue the original task", output["systemMessage"].casefold())
        self.assertIsNone(
            HANDOFF_GUARDS.guard_tool(
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
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=request),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
        ):
            self.assertIsNone(evaluate_request(self.event))
        raw = (
            Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl"
        ).read_text()
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
        self.assertIsNone(HANDOFF_GUARDS.guard_replay_answer(event))
        saved = HANDOFF_STATE.read_state(HANDOFF_STATE.state_path(self.thread_id))
        self.assertEqual(saved["phase"], "passed")
        self.assertEqual(saved["assessment_generation"], "retained-generation")
        self.assertNotIn("pending_assessment", saved)
        self.assertIsNone(
            HANDOFF_GUARDS.guard_tool(
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
                HANDOFF_GUARDS.guard_replay_answer(
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

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def source_response(self, content=None):
        return {
            "data": [
                {
                    "item": {
                        "type": "userMessage",
                        "content": content or [{"type": "text", "text": self.prompt}],
                    }
                }
            ],
            "nextCursor": None,
        }

    def queue_receipt(self, content=None):
        return {
            "queuedSubmission": {
                "id": "queued-1",
                "input": copy.deepcopy(
                    content or [{"type": "text", "text": self.prompt}]
                ),
            }
        }

    def stage(self, target_model="gpt-6-sol"):
        state = {
            "phase": "ready",
            "created_at": int(time.time()),
            "source_turn_id": self.turn_id,
            "prompt": self.prompt,
            "prompt_digest": HANDOFF_INPUT.prompt_digest(self.prompt),
            "target_model": target_model,
            "target_effort": "medium",
            "official_source_url": self.recommendation["official_source_url"],
            "official_guidance": self.recommendation["official_guidance"],
            "task_inference": self.recommendation["task_inference"],
        }
        path = HANDOFF_STATE.state_path(self.thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        HANDOFF_STATE.write_state(path, state)
        return path

    def prepare_ready(self, event):
        with (
            patch.object(
                HANDOFF_PREPARATION,
                "session_input",
                return_value={"task": event["prompt"], "active_profile": self.active},
            ),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value=self.recommendation
            ),
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
        ):
            reader.return_value.__enter__.return_value.call.return_value = {
                "data": [],
                "nextCursor": None,
            }
            return evaluate_request(event)

    def stage_replay(self, content=None):
        content = content or [{"type": "text", "text": self.prompt}]
        queued = copy.deepcopy(content)
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.pop("prompt")
        state.update(
            phase="queued",
            replay_turn_id="replay-turn",
            queued_input_digest=HANDOFF_INPUT.input_digest(queued),
        )
        HANDOFF_STATE.write_state(path, state)
        return (content, queued)

    def test_recommendation_stages_exact_prompt_for_control_only_turn(self):
        request = {"task": self.prompt, "active_profile": self.active}
        with (
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=request),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value=self.recommendation
            ),
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=request),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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
                HANDOFF_PREPARATION,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
        ):
            self.assertIsNone(evaluate_request(self.event))
        with (
            patch.object(
                HANDOFF_PREPARATION,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value=self.recommendation
            ) as triage,
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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
            HANDOFF_GUARDS.guard_tool(tool_event)["hookSpecificOutput"][
                "permissionDecision"
            ],
            "deny",
        )
        audit = (
            (Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl")
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
        bound = HANDOFF_GUARDS.guard_tool(switch)["hookSpecificOutput"]
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
        queued = HANDOFF_GUARDS.guard_tool(
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
            denied = HANDOFF_GUARDS.guard_tool(
                {**switch, "tool_name": "Bash", "tool_input": {"command": command}}
            )
            self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(
            HANDOFF_GUARDS.guard_tool({**switch, "turn_id": "another-turn"})[
                "hookSpecificOutput"
            ]["permissionDecision"],
            "deny",
        )

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
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                response,
                self.queue_receipt(content),
            ]
            self.assertEqual(
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)["status"],
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
            HANDOFF_GUARDS.guard_tool(
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
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                self.source_response([content[1]]),
                self.queue_receipt(content),
            ]
            self.assertEqual(
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)["status"],
                "queued",
            )
            self.assertEqual(
                app.call.call_args_list[-1].args[1]["input"][0], content[0]
            )

    def test_control_message_is_not_replayed_as_user_work(self):
        path = self.stage()
        evaluate_request(
            dict(
                self.event,
                turn_id="control-turn",
                prompt=HOOKS_INSTRUCTIONS.CONTROL_PROMPT,
            )
        )
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
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
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)["status"],
                "queued",
            )
            self.assertEqual(len(app.call.call_args_list[-1].args[1]["input"]), 1)
        self.assertNotIn("prompt", HANDOFF_STATE.read_state(path))

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
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(source),
                self.source_response([correction]),
                {"queuedSubmission": {"id": "queued-1", "input": queued}},
            ]
            HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
        native_prompt = self.prompt + "Add correction: true"
        with (
            patch.object(
                HANDOFF_PREPARATION,
                "session_input",
                return_value={
                    "active_profile": {
                        "model": "gpt-6-sol",
                        "effort": "medium",
                        "speed": None,
                    }
                },
            ),
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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
            HANDOFF_PREPARATION.submit_prompt(
                dict(self.event, turn_id="replay-turn", prompt=native_prompt)
            )
            result = HANDOFF_PREPARATION.assess_submitted()
        self.assertEqual(
            result["hookSpecificOutput"]["additionalContext"],
            HOOKS_INSTRUCTIONS.REPLAY_CONTEXT,
        )
        self.assertEqual(
            HANDOFF_STATE.read_state(path)["replay_turn_id"], "replay-turn"
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

    def test_queue_requires_target_profile_and_matching_turn(self):
        path = self.stage()
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.return_value = {
                "thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}
            }
            with self.assertRaisesRegex(ValueError, "Target profile"):
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
            self.assertEqual(app.call.call_count, 1)
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "ready")
        with self.assertRaisesRegex(ValueError, "No matching"):
            HANDOFF_QUEUE.enqueue_handoff(self.thread_id, "other-turn")
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "ready")

    def test_queue_runs_once_and_drops_prompt_from_state(self):
        path = self.stage()
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                self.queue_receipt(),
            ]
            self.assertEqual(
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)["status"],
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
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            self.assertEqual(
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id),
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
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(content),
                self.queue_receipt(content),
            ]
            HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
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
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(content),
                {"queuedSubmission": {"id": "queued-1", "input": native}},
            ]
            self.assertEqual(
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)["status"],
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
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(content),
                self.queue_receipt(content),
            ]
            HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
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
                with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
                    app = reader.return_value.__enter__.return_value
                    app.call.side_effect = [
                        {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                        response,
                    ]
                    with self.assertRaisesRegex(ValueError, "Source user input"):
                        HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
                    self.assertNotIn(
                        "thread/queue/add", [c.args[0] for c in app.call.call_args_list]
                    )
                self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "ready")

    def test_source_input_follows_native_pagination(self):
        source = [{"type": "text", "text": self.prompt}]
        steering = [{"type": "image", "url": "data:image/png;base64,aW1hZ2U="}]
        for source_page in (0, 6):
            with self.subTest(source_page=source_page):
                app = MagicMock()
                pages = [
                    {
                        "data": [{"item": {"type": "agentMessage"}}] * 100,
                        "nextCursor": f"page-{index + 1}",
                    }
                    for index in range(7)
                ]
                pages[source_page]["data"][0] = {
                    "item": {"type": "userMessage", "content": source}
                }
                pages.append(self.source_response(steering))
                app.call.side_effect = pages
                self.assertEqual(
                    HANDOFF_CODEX.source_input(
                        app, self.thread_id, self.turn_id, include_steering=True
                    ),
                    source + steering,
                )

    def test_source_input_rejects_repeated_native_cursor(self):
        app = MagicMock()
        app.call.side_effect = [
            {"data": [], "nextCursor": "repeated"},
            {"data": [], "nextCursor": "repeated"},
        ]
        with self.assertRaisesRegex(ValueError, "pagination repeated a cursor"):
            HANDOFF_CODEX.source_input(
                app, self.thread_id, self.turn_id, include_steering=True
            )

    def test_source_input_timeout_never_returns_partial_input(self):
        app = MagicMock()
        app.call.return_value = {
            **self.source_response([{"type": "text", "text": self.prompt}]),
            "nextCursor": "next",
        }
        with patch.object(HANDOFF_CODEX.time, "monotonic", side_effect=[0, 0, 51]):
            with self.assertRaises(TimeoutError):
                HANDOFF_CODEX.source_input(
                    app, self.thread_id, self.turn_id, include_steering=True
                )

    def test_same_text_in_new_turn_replaces_pending_native_message(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
        HANDOFF_STATE.write_state(path, state)
        with (
            patch.object(
                HANDOFF_PREPARATION,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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
                with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
                    app = reader.return_value.__enter__.return_value
                    app.call.side_effect = [
                        {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                        self.source_response(content),
                        {"queuedSubmission": receipt},
                    ]
                    with self.assertRaisesRegex(
                        ValueError, "receipt input is unavailable"
                    ):
                        HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
                    self.assertNotIn(
                        "thread/queue/delete",
                        [c.args[0] for c in app.call.call_args_list],
                    )
                self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "attempting")
                self.assertEqual(
                    HANDOFF_STATE.read_state(path)["queued_submission_id"], "queued-1"
                )
                with self.assertRaisesRegex(RuntimeError, "do not retry"):
                    HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)

    def test_incomplete_preparation_cannot_start_native_queue_io(self):
        for missing in ("target_effort", "created_at", "prompt"):
            with self.subTest(missing=missing):
                path = self.stage()
                state = HANDOFF_STATE.read_state(path)
                state.pop(missing)
                HANDOFF_STATE.write_state(path, state)
                before = path.read_bytes()
                with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
                    with self.assertRaises(ValueError):
                        HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
                    reader.assert_not_called()
                self.assertEqual(path.read_bytes(), before)

    def test_terminal_turn_with_lost_attachment_does_not_confirm_replay(self):
        queued = copy.deepcopy(
            [
                {"type": "text", "text": self.prompt},
                {"type": "image", "url": "same-image"},
            ]
        )
        replay = UnboundReplay(
            self.turn_id,
            100,
            TransferInputEvidence("native_input", HANDOFF_INPUT.input_digest(queued)),
        )
        with patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {
                    "data": [
                        {"id": "replay-turn", "startedAt": 101, "status": "completed"}
                    ]
                },
                self.source_response([queued[0]]),
            ]
            self.assertFalse(HANDOFF_CODEX.replay_finished(app, self.thread_id, replay))

    def test_uncertain_queue_attempt_is_not_retried(self):
        path = self.stage()
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                TimeoutError("unknown outcome"),
            ]
            with self.assertRaises(TimeoutError):
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
        state = HANDOFF_STATE.read_state(path)
        self.assertEqual(state["phase"], "attempting")
        self.assertNotIn("prompt", state)
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            with self.assertRaisesRegex(RuntimeError, "do not retry"):
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
            reader.assert_not_called()

    def test_explicit_queue_rejection_clears_handoff(self):
        path = self.stage()
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                CODEX_CONNECTION.AppServerRPCError(
                    "thread/queue/add: queue cannot contain more than 100 submissions"
                ),
            ]
            with self.assertRaises(CODEX_CONNECTION.AppServerRPCError):
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "rejected")
        guard_event = {
            "session_id": self.thread_id,
            "turn_id": self.turn_id,
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -c 'print(1)'"},
        }
        self.assertEqual(
            HANDOFF_GUARDS.guard_tool(guard_event)["hookSpecificOutput"][
                "permissionDecision"
            ],
            "deny",
        )
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
        self.assertEqual(evaluate_request(self.event)["decision"], "block")
        next_event = dict(self.event, turn_id="new-turn")
        with (
            patch.object(
                HANDOFF_PREPARATION,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
        ):
            self.assertIsNone(evaluate_request(next_event))
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")

    def test_json_rpc_rejection_has_distinct_exception(self):
        reader = object.__new__(HANDOFF_CODEX.AppServerReader)
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
            with self.assertRaisesRegex(
                CODEX_CONNECTION.AppServerRPCError, "queue full"
            ):
                reader.call("thread/queue/add", {}, 1)

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
                with patch.object(HANDOFF_QUEUE.time, "time", return_value=4000):
                    result = HANDOFF_GUARDS.guard_tool(event)
                if result is not None:
                    self.assertEqual(
                        result["hookSpecificOutput"]["permissionDecision"], "allow"
                    )
                self.assertEqual(HANDOFF_STATE.read_state(path)["created_at"], 0)
                with (
                    patch.object(HANDOFF_QUEUE.time, "time", return_value=4001),
                    patch.object(HANDOFF_QUEUE, "AppServerReader") as reader,
                ):
                    app = reader.return_value.__enter__.return_value
                    app.call.side_effect = [
                        {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                        self.source_response(),
                        self.queue_receipt(),
                    ]
                    self.assertEqual(
                        HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)[
                            "status"
                        ],
                        "queued",
                    )
                    self.assertEqual(
                        app.call.call_args_list[-1].args[1]["input"],
                        [{"type": "text", "text": self.prompt}],
                    )
                    self.assertEqual(
                        HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)[
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
                result = HANDOFF_GUARDS.guard_tool(
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
                    HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)

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
        with patch.object(HANDOFF_QUEUE.time, "time", return_value=4000):
            self.assertIsNone(HANDOFF_GUARDS.guard_tool(event))
        before = path.read_bytes()
        with (
            patch.object(HANDOFF_QUEUE.time, "time", return_value=4301),
            self.assertRaisesRegex(ValueError, "expired"),
        ):
            HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
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
            HANDOFF_GUARDS.NativeTransferTools, "matches_queue", side_effect=changed
        ):
            result = HANDOFF_GUARDS.guard_tool(
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

    def test_expired_handoff_cannot_queue_old_task(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state["created_at"] = 0
        HANDOFF_STATE.write_state(path, state)
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            with self.assertRaisesRegex(ValueError, "expired"):
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)
            reader.assert_not_called()

    def test_other_thread_cannot_queue_handoff(self):
        self.stage()
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "another-thread"}):
            with self.assertRaisesRegex(ValueError, "target Desktop thread"):
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)

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
        self.assertIsNone(HANDOFF_GUARDS.guard_tool(event))
        event["tool_name"] = "Bash"
        event["tool_input"] = {
            "command": HOOKS_INSTRUCTIONS.queue_command(self.thread_id, self.turn_id)
        }
        self.assertIsNone(HANDOFF_GUARDS.guard_tool(event))
        event["tool_input"] = {"command": "python3 -c 'print(1)'"}
        self.assertEqual(
            HANDOFF_GUARDS.guard_tool(event)["hookSpecificOutput"][
                "permissionDecision"
            ],
            "deny",
        )
        event["turn_id"] = "another-turn"
        self.assertIsNone(HANDOFF_GUARDS.guard_tool(event))

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
                self.assertIsNone(HANDOFF_GUARDS.guard_tool(event))
            for field in arguments:
                with self.subTest(tool=tool, wrong=field):
                    wrong = dict(event, tool_input=dict(arguments, **{field: "wrong"}))
                    output = HANDOFF_GUARDS.guard_tool(wrong)["hookSpecificOutput"]
                    self.assertEqual(
                        output["permissionDecision"],
                        "allow" if field == "threadId" else "deny",
                    )
                    if field == "threadId":
                        self.assertEqual(output["updatedInput"], arguments)
        event["tool_name"] = "other_codex_appsend_message_to_thread"
        self.assertEqual(
            HANDOFF_GUARDS.guard_tool(event)["hookSpecificOutput"][
                "permissionDecision"
            ],
            "deny",
        )

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
                    patch.object(
                        HANDOFF_PREPARATION, "session_input", return_value=request
                    ),
                    patch.object(
                        HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
                    ) as triage,
                    patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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
                    HANDOFF_GUARDS.guard_tool(
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
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=request),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "unknown"}
            ) as triage,
        ):
            output = evaluate_request(event)
        triage.assert_called_once()
        self.assertNotEqual(output.get("decision"), "block")
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")
        self.assertIsNone(
            HANDOFF_GUARDS.guard_tool(
                {**event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )
        audit = (
            Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl"
        ).read_text()
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
                HANDOFF_PREPARATION,
                "session_input",
                side_effect=RuntimeError("temporary input read failure"),
            ),
            self.assertRaises(RuntimeError),
        ):
            evaluate_request(event)
        self.assertEqual(HANDOFF_STATE.read_state(path), prior)
        with (
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=request),
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
            self.assertRaises(TimeoutError),
        ):
            reader.return_value.__enter__.return_value.call.side_effect = TimeoutError(
                "temporary history read failure"
            )
            evaluate_request(event)
        self.assertEqual(HANDOFF_STATE.read_state(path), prior)
        with (
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=request),
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
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
                HANDOFF_PREPARATION,
                "session_input",
                return_value={"task": choice, "active_profile": self.active},
            ),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
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
                patch.object(
                    HANDOFF_PREPARATION, "session_input", return_value=request
                ),
                patch.object(
                    HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
                ) as triage,
                patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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
                HANDOFF_PREPARATION,
                "session_input",
                return_value={"task": event["prompt"], "active_profile": self.active},
            ),
            patch.object(HANDOFF_PREPARATION, "triage", side_effect=concurrent_queue),
        ):
            output = evaluate_request(event)
        self.assertEqual(output["decision"], "block")
        self.assertEqual(
            HANDOFF_STATE.read_state(path)["queued_submission_id"], "concurrent-queue"
        )
        self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "queued")

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
            result = HANDOFF_GUARDS.guard_tool(event)
            elapsed = time.monotonic() - started
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "busy", result["hookSpecificOutput"]["permissionDecisionReason"].casefold()
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
            result = HANDOFF_GUARDS.guard_tool(event)
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
        self.assertIsNone(HANDOFF_GUARDS.guard_tool(event))
        with HANDOFF_STATE.locked_state(
            self.thread_id, operation="pre_tool_use", turn_id="replay-turn"
        ):
            self.assertIsNone(HANDOFF_GUARDS.guard_tool(event))
        self.assertEqual(HANDOFF_STATE.read_state(path), state)
        audit = (
            Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl"
        )
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
                result = HANDOFF_GUARDS.guard_tool(
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
                HANDOFF_GUARDS.guard_tool(event)["hookSpecificOutput"][
                    "permissionDecision"
                ],
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
        victim = Path(self.temporary.name) / "victim.txt"
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
            result = HANDOFF_GUARDS.guard_tool(event)
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
            (Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl")
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
            HANDOFF_GUARDS.guard_tool(event)["hookSpecificOutput"][
                "permissionDecision"
            ],
            "deny",
        )

    def test_steer_in_queued_source_turn_preserves_tool_guard(self):
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.pop("prompt")
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
        HANDOFF_STATE.write_state(path, state)
        steered = dict(self.event, prompt="Show the backlog")
        with patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader:
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
            HANDOFF_GUARDS.guard_tool(tool_event)["hookSpecificOutput"][
                "permissionDecision"
            ],
            "deny",
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
                HANDOFF_PREPARATION,
                "session_input",
                return_value={
                    "task": "Show the backlog",
                    "active_profile": self.active,
                },
            ),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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
        with patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader:
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
                HANDOFF_PREPARATION,
                "session_input",
                return_value={
                    "task": "Show the backlog",
                    "active_profile": self.active,
                },
            ),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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

    def test_terminal_replay_beyond_first_page_releases_guard(self):
        replay = BoundReplay("replay-turn")
        with patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {
                    "data": [
                        {"id": f"blocked-{i}", "startedAt": 103, "status": "completed"}
                        for i in range(5)
                    ],
                    "nextCursor": "older",
                },
                {
                    "data": [
                        {"id": "replay-turn", "startedAt": 101, "status": "failed"}
                    ],
                    "nextCursor": None,
                },
            ]
            self.assertTrue(HANDOFF_CODEX.replay_finished(app, self.thread_id, replay))
            self.assertEqual(app.call.call_args_list[1].args[1]["cursor"], "older")

    def test_bound_replay_started_before_queue_receipt_is_still_terminal(self):
        replay = BoundReplay("replay-turn")
        with patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.return_value = {
                "data": [
                    {"id": "replay-turn", "startedAt": 101, "status": "completed"}
                ],
                "nextCursor": None,
            }
            self.assertTrue(HANDOFF_CODEX.replay_finished(app, self.thread_id, replay))

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
                HANDOFF_PREPARATION,
                "session_input",
                return_value={"task": "new work", "active_profile": self.active},
            ),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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

    def test_unbound_running_turn_or_missing_source_cannot_release_guard(self):
        for turns in [
            [
                {"id": "unbound", "status": "inProgress"},
                {"id": self.turn_id, "status": "completed"},
            ],
            [{"id": "other", "status": "completed"}],
            [{"id": self.turn_id, "status": "inProgress"}],
        ]:
            with (
                self.subTest(turns=turns),
                patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
            ):
                app = reader.return_value.__enter__.return_value
                app.call.return_value = {"data": turns, "nextCursor": None}
                self.assertFalse(
                    HANDOFF_CODEX.source_terminal_without_replay(
                        app, self.thread_id, self.turn_id, "new-turn"
                    )
                )

    def test_handoff_history_repeated_cursor_retains_unknown_outcome(self):
        with patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.return_value = {"data": [], "nextCursor": "repeated"}
            with self.assertRaisesRegex(ValueError, "cursor repeated"):
                HANDOFF_CODEX.source_terminal_without_replay(
                    app, self.thread_id, self.turn_id, "new-turn"
                )

    def test_old_identical_prompt_does_not_confirm_replay(self):
        replay = UnboundReplay(
            self.turn_id,
            100,
            TransferInputEvidence(
                "legacy_prompt", HANDOFF_INPUT.prompt_digest(self.prompt)
            ),
        )
        with patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.return_value = {
                "data": [
                    {
                        "id": "old-turn",
                        "startedAt": 99,
                        "completedAt": 99,
                        "status": "completed",
                    }
                ],
                "nextCursor": None,
            }
            self.assertFalse(HANDOFF_CODEX.replay_finished(app, self.thread_id, replay))
            self.assertEqual(app.call.call_count, 1)

    def test_queue_scan_stops_after_bounded_pages(self):
        with patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"data": [], "nextCursor": f"cursor-{index}"}
                for index in range(HANDOFF_CODEX.MAX_QUEUE_PAGES)
            ]
            with self.assertRaisesRegex(ValueError, "bounded"):
                HANDOFF_CODEX.queued_ids(app, self.thread_id)
            self.assertEqual(app.call.call_count, HANDOFF_CODEX.MAX_QUEUE_PAGES)

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
                HANDOFF_PREPARATION,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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
        with patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader:
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
                        HANDOFF_PREPARATION,
                        "session_input",
                        return_value={
                            "task": "Show the backlog",
                            "active_profile": self.active,
                        },
                    ),
                    patch.object(
                        HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
                    ),
                    patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
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
        with patch.object(HANDOFF_QUEUE, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-sol", "reasoningEffort": "medium"}},
                self.source_response(),
                self.queue_receipt(),
            ]
            self.assertEqual(
                HANDOFF_QUEUE.enqueue_handoff(self.thread_id, self.turn_id)["status"],
                "queued",
            )
        replay = dict(
            self.event, turn_id="replay-turn", prompt=self.prompt, model="gpt-6-sol"
        )
        with (
            patch.object(HANDOFF_QUEUE, "AppServerReader") as reader,
            patch.object(
                HANDOFF_PREPARATION,
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
            HANDOFF_PREPARATION.submit_prompt(replay)
            output = HANDOFF_PREPARATION.assess_submitted()
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
                            denied = HANDOFF_GUARDS.guard_tool(event)
                    else:
                        denied = HANDOFF_GUARDS.guard_tool(event)
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
                HANDOFF_GUARDS.guard_tool(
                    dict(replay, tool_name=tool, tool_input=arguments)
                )
            )
        self.assertEqual(path.read_bytes(), saved)

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
                HANDOFF_PREPARATION,
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
            (Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        outcomes = [json.loads(line)["outcome"] for line in audit]
        self.assertEqual(outcomes.count("auto_started"), 1)
        self.assertEqual(outcomes.count("auto_deferred"), 1)
        self.assertLess(outcomes.index("auto_started"), outcomes.index("auto_deferred"))
        self.assertNotIn("auto_handoff", outcomes)

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
        audit = (
            Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl"
        ).read_text()
        failure = json.loads(audit.splitlines()[-1])
        self.assertEqual(failure["outcome"], "auto_queue_error:RuntimeError")
        self.assertEqual(failure["details"]["hook_event"], "queue")
        self.assertIn("failure_line", failure["details"])
        self.assertNotIn("private request text", audit + error_output.getvalue())

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
        audit = (
            Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl"
        ).read_text()
        self.assertEqual(json.loads(audit)["outcome"], "auto_error:ValueError")
        self.assertNotIn("private request text", audit)

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
            patch.object(HANDOFF_GUARDS, "AppServerReader") as reader,
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
            result = HANDOFF_GUARDS.guard_replay_answer(event)
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
        with patch.object(HANDOFF_GUARDS, "AppServerReader") as reader:
            self.assertIsNone(HANDOFF_GUARDS.guard_replay_answer(event))
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
            patch.object(HANDOFF_GUARDS, "AppServerReader") as reader,
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
            self.assertIsNone(HANDOFF_GUARDS.guard_replay_answer(event))
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
            patch.object(HANDOFF_GUARDS, "AppServerReader") as reader,
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
            self.assertIsNone(HANDOFF_GUARDS.guard_replay_answer(event))
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
            patch.object(HANDOFF_GUARDS, "AppServerReader") as reader,
            patch("vector_prime.entrypoints.hooks.operations.check_answer") as classify,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                self.source_response(original),
                {
                    "data": [{"item": {"type": "userMessage", "content": queued}}],
                    "nextCursor": None,
                },
            ]
            self.assertIsNone(HANDOFF_GUARDS.guard_replay_answer(event))
            classify.assert_not_called()
        with (
            patch.object(HANDOFF_GUARDS, "AppServerReader") as reader,
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
            self.assertIsNone(HANDOFF_GUARDS.guard_replay_answer(event))
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
            (Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        self.assertEqual(json.loads(audit[-1])["outcome"], "auto_error:RuntimeError")


if __name__ == "__main__":
    unittest.main()
