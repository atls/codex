from fixtures.autoswitch.assessment import evaluate_request
from fixtures.autoswitch.lock import held_lock, write_concurrent_state

"""Unavailable native history and protected handoff behavior with simulated API failures."""

import io
import json
import unittest

import pytest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import MagicMock, patch

import vector_prime.entrypoints.hooks.instructions as HOOKS_INSTRUCTIONS
import vector_prime.entrypoints.hooks.native_contract as DESKTOP_CONFIGURATION
from vector_prime.entrypoints.hooks import operations
import vector_prime.application.submission.helpers.content as HANDOFF_INPUT
import vector_prime.infrastructure.adapters.codex.transport.connection as CODEX_CONNECTION
import vector_prime.infrastructure.adapters.filesystem.cache as RECOMMENDATION_STORE
import vector_prime.infrastructure.adapters.filesystem.state as HANDOFF_STATE
import vector_prime.entrypoints.hooks.handlers.assessment as CLI
import vector_prime.entrypoints.hooks.events.dispatch as EVENTS


class UnavailableSourceTests(unittest.TestCase):
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "thread",
        "turn_id": "turn",
        "cwd": "/fixture",
        "model": "gpt-6-luna",
        "prompt": "ordinary request",
    }

    @pytest.fixture(autouse=True)
    def isolated_codex(self, codex_home, monkeypatch):
        self.home = codex_home
        monkeypatch.setenv("CODEX_THREAD_ID", "thread")
        monkeypatch.setenv(DESKTOP_CONFIGURATION.AUTO_THREAD_ENV, "thread")

    def error(self, **changes):
        fields = {
            "method": "thread/read",
            "code": -32600,
            "thread_id": "thread",
        } | changes
        message = fields.pop("message", "thread not loaded: thread")
        return CODEX_CONNECTION.AppServerRPCError(message, **fields)

    def invoke(self, error, event=None):
        output = io.StringIO()
        submitted = io.StringIO()
        with (
            patch("sys.argv", ["desktop.py"]),
            patch("sys.stdin", io.StringIO(json.dumps(event or self.event))),
            patch.object(operations, "session_input", side_effect=error),
            patch.object(operations, "triage") as triage,
            patch.object(operations, "AppServerReader") as reader,
        ):
            with redirect_stdout(submitted):
                self.assertEqual(EVENTS.handle_event(), 0)
            stage = json.loads(submitted.getvalue())
            if stage.get("decision") == "block":
                return stage
            with redirect_stdout(output):
                CLI.assess_current()
            triage.assert_not_called()
            reader.assert_not_called()
        return json.loads(output.getvalue())

    def write(self, state):
        path = HANDOFF_STATE.state_path("thread")
        path.parent.mkdir(parents=True, exist_ok=True)
        HANDOFF_STATE.write_state(path, state)
        return path

    def accepted_reader(self):
        reader = MagicMock()
        reader.__enter__.return_value.call.return_value = {
            "data": [
                {
                    "item": {
                        "id": "native-message",
                        "type": "userMessage",
                        "content": [{"type": "text", "text": self.event["prompt"]}],
                    }
                }
            ],
            "nextCursor": None,
        }
        return reader

    def test_same_thread_structured_capability_failure_warns_without_reconstructing_or_triage(
        self,
    ):
        output = self.invoke(self.error())
        self.assertEqual(set(output), {"systemMessage"})
        self.assertIn("suitability is unknown", output["systemMessage"].casefold())
        self.assertEqual(
            {
                key: value
                for key, value in HANDOFF_STATE.read_state(
                    HANDOFF_STATE.state_path("thread")
                ).items()
                if key != "assessment_generation"
            },
            {
                "phase": "passed",
                "source_turn_id": "turn",
                "assessment_decision": "unknown",
            },
        )
        self.assertIsNone(
            operations.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )
        rows = [
            json.loads(line)
            for line in (self.home / ".tmp/model-fit-hook-audit/thread.jsonl")
            .read_text()
            .splitlines()
        ]
        self.assertEqual(
            next(row for row in rows if row["outcome"] == "auto_session_unavailable")[
                "details"
            ]["reason_code"],
            "session_thread_not_loaded",
        )

    def test_exact_ephemeral_turns_unsupported_does_not_invent_numeric_code(self):
        output = self.invoke(
            self.error(
                method="thread/turns/list",
                code=None,
                message="ephemeral threads do not support thread/turns/list",
            )
        )
        self.assertEqual(set(output), {"systemMessage"})

    def test_generic_failures_continue_without_claiming_a_specific_capability(self):
        cases = [
            self.error(code=-32000),
            self.error(code="-32600"),
            self.error(method="thread/resume"),
            self.error(thread_id="other"),
            self.error(message="thread not loaded: other"),
            self.error(message="thread not loaded: thread extra"),
            self.error(
                method="thread/turns/list",
                message="ephemeral threads do not support thread/turns/list extra",
            ),
            TimeoutError("timeout"),
            RuntimeError("app-server closed stdout"),
            RuntimeError("auth"),
            ValueError("malformed"),
        ]
        for error in cases:
            with self.subTest(error=str(error)):
                output = self.invoke(error)
                self.assertIn(
                    "continue the original task", output["systemMessage"].casefold()
                )
                self.assertEqual(
                    HANDOFF_STATE.read_state(HANDOFF_STATE.state_path("thread"))[
                        "assessment_decision"
                    ],
                    "unknown",
                )

    def test_technical_control_is_not_an_ordinary_capability_fallback(self):
        output = self.invoke(
            self.error(), dict(self.event, prompt=HOOKS_INSTRUCTIONS.CONTROL_PROMPT)
        )
        self.assertEqual(output["decision"], "block")

    def test_previous_admitted_turn_does_not_prevent_new_ordinary_warning(self):
        self.write({"phase": "passed", "source_turn_id": "previous"})
        self.assertIn("systemMessage", self.invoke(self.error()))
        self.assertEqual(
            HANDOFF_STATE.read_state(HANDOFF_STATE.state_path("thread"))[
                "source_turn_id"
            ],
            "turn",
        )

    def test_pending_and_unknown_attempt_states_remain_protected(self):
        for phase in ["ready", "attempting", "queued"]:
            with self.subTest(phase=phase):
                state = {
                    "phase": phase,
                    "source_turn_id": "source",
                    "prompt": "original",
                    "prompt_digest": "original",
                    "queued_submission_id": "queued",
                }
                path = self.write(state)
                before = path.read_bytes()
                event = (
                    dict(self.event, turn_id="source")
                    if phase == "queued"
                    else self.event
                )
                output = self.invoke(self.error(), event)
                if phase == "attempting":
                    self.assertEqual(output["decision"], "block")
                    self.assertEqual(path.read_bytes(), before)
                elif phase == "ready":
                    self.assertIn(
                        "continue the original task", output["systemMessage"].casefold()
                    )
                    self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")
                    continue
                else:
                    self.assertEqual(output["status"], "failed")
                    self.assertEqual(
                        {key: HANDOFF_STATE.read_state(path)[key] for key in state},
                        state,
                    )
                self.assertEqual(
                    operations.guard_tool(
                        {
                            **event,
                            "turn_id": "source",
                            "tool_name": "Bash",
                            "tool_input": {"command": "pwd"},
                        }
                    )["hookSpecificOutput"]["permissionDecision"],
                    "deny",
                )

    def test_concurrent_handoff_is_not_replaced_by_passed_admission(self):
        for phase in ["ready", "attempting", "queued"]:
            path = HANDOFF_STATE.state_path("thread")
            path.unlink(missing_ok=True)
            state = {"phase": phase, "source_turn_id": "concurrent"}

            def unavailable(_):
                self.write(state)
                raise self.error()

            with self.subTest(phase=phase):
                self.assertIn(
                    "superseded",
                    self.invoke(unavailable)["hookSpecificOutput"][
                        "additionalContext"
                    ].casefold(),
                )
                self.assertEqual(HANDOFF_STATE.read_state(path), state)

    def test_damaged_or_symlink_state_is_not_absence(self):
        path = HANDOFF_STATE.state_path("thread")
        path.parent.mkdir(parents=True)
        for value in ["not json", '{"phase":"unknown"}']:
            path.write_text(value)
            self.assertEqual(self.invoke(self.error())["decision"], "block")
            self.assertEqual(path.read_text(), value)
        path.unlink()
        path.symlink_to(path.parent / "missing")
        self.assertEqual(self.invoke(self.error())["decision"], "block")
        self.assertTrue(path.is_symlink())

    def test_busy_lock_from_another_process_during_read_is_not_absence(self):
        with ExitStack() as locks:

            def unavailable(_):
                locks.enter_context(held_lock("thread"))
                raise self.error()

            self.assertEqual(self.invoke(unavailable)["status"], "failed")
            self.assertEqual(
                HANDOFF_STATE.read_state(HANDOFF_STATE.state_path("thread"))[
                    "pending_assessment"
                ]["status"],
                "running",
            )

    def test_same_capability_error_from_triage_is_not_session_input_fallback(self):
        operations.submit_prompt(self.event)
        output = io.StringIO()
        with (
            patch("sys.argv", ["desktop.py"]),
            patch("sys.stdin", io.StringIO(json.dumps(self.event))),
            patch.object(
                operations,
                "session_input",
                return_value={
                    "task": "request",
                    "active_profile": {
                        "model": "gpt-6-luna",
                        "effort": "low",
                        "speed": None,
                    },
                },
            ),
            patch.object(operations, "triage", side_effect=self.error()),
            patch.object(
                operations,
                "AppServerReader",
                return_value=self.accepted_reader(),
            ),
            redirect_stdout(output),
        ):
            CLI.assess_current()
        self.assertIn(
            "continue the original task",
            json.loads(output.getvalue())["systemMessage"].casefold(),
        )

    def test_preserved_profile_choice_context_is_not_a_fresh_fallback(self):
        state = {
            "phase": "passed",
            "source_turn_id": "previous",
            "profile_context_turn_id": "choice",
        }
        path = self.write(state)
        self.assertIn(
            "continue the original task",
            self.invoke(self.error())["systemMessage"].casefold(),
        )
        self.assertEqual(
            HANDOFF_STATE.read_state(path)["profile_context_turn_id"], "choice"
        )

    def test_empty_prompt_with_two_attachment_sentinels_is_not_reconstructed_or_replaced(
        self,
    ):
        event = {
            **self.event,
            "prompt": "",
            "attachments": [{"sentinel": "first"}, {"sentinel": "second"}],
        }
        output = self.invoke(self.error(), event)
        self.assertEqual(set(output), {"systemMessage"})
        self.assertNotIn("sentinel", str(output))
        self.assertEqual(
            {
                key: value
                for key, value in HANDOFF_STATE.read_state(
                    HANDOFF_STATE.state_path("thread")
                ).items()
                if key != "assessment_generation"
            },
            {
                "phase": "passed",
                "source_turn_id": "turn",
                "assessment_decision": "unknown",
            },
        )

    def recommendation(self):
        return {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "active_speed": None,
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "medium",
            "recommended_speed": None,
            "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
            "official_guidance": "Choose the capability required by the task.",
            "task_inference": "This work requires more capability.",
            "reason": "bounded recommendation",
        }

    def stage_manual_block(self, event=None):
        event = event or self.event
        request = {
            "task": event["prompt"] or "attachment request",
            "active_profile": {"model": "gpt-6-luna", "effort": "low", "speed": None},
        }
        with (
            patch.object(operations, "session_input", return_value=request),
            patch.object(operations, "triage", return_value=self.recommendation()),
            patch.object(
                operations,
                "AppServerReader",
                side_effect=RuntimeError("queue unavailable"),
            ),
        ):
            result = evaluate_request(event)
        self.assertEqual(result["decision"], "block")
        self.assertIsNone(HANDOFF_STATE.read_state(HANDOFF_STATE.state_path("thread")))
        self.assertIsNotNone(
            RECOMMENDATION_STORE.load_pending(
                RECOMMENDATION_STORE.pending_path("thread")
            )
        )
        return request

    def test_source_unavailable_releases_unqueued_recommendation(self):
        self.stage_manual_block()
        output = self.invoke(self.error(), dict(self.event, turn_id="second"))
        self.assertNotEqual(output.get("decision"), "block")
        self.assertIn("suitability is unknown", output["systemMessage"].casefold())
        self.assertEqual(
            HANDOFF_STATE.read_state(HANDOFF_STATE.state_path("thread"))["phase"],
            "passed",
        )
        self.assertFalse(RECOMMENDATION_STORE.pending_path("thread").exists())

    def test_media_source_unavailable_does_not_reconstruct_input_or_block(self):
        event = {
            **self.event,
            "prompt": "",
            "attachments": [{"sentinel": "first"}, {"sentinel": "second"}],
        }
        self.stage_manual_block(event)
        output = self.invoke(self.error(), dict(event, turn_id="second"))
        self.assertNotEqual(output.get("decision"), "block")
        self.assertFalse(RECOMMENDATION_STORE.pending_path("thread").exists())
        self.assertEqual(
            HANDOFF_STATE.read_state(HANDOFF_STATE.state_path("thread"))["phase"],
            "passed",
        )

    def test_other_nonempty_work_is_not_a_global_deny_and_does_not_guess_clearance(
        self,
    ):
        self.stage_manual_block()
        before = RECOMMENDATION_STORE.pending_path("thread").read_bytes()
        output = self.invoke(
            self.error(),
            dict(self.event, turn_id="second", prompt="different bounded request"),
        )
        self.assertEqual(set(output), {"systemMessage"})
        self.assertEqual(
            RECOMMENDATION_STORE.pending_path("thread").read_bytes(), before
        )

    def test_native_selected_recommended_profile_can_clear_manual_evidence(self):
        self.stage_manual_block()
        selected = {
            "task": self.event["prompt"],
            "active_profile": {
                "model": "gpt-6.1-sol",
                "effort": "medium",
                "speed": None,
            },
        }
        with (
            patch.object(operations, "session_input", return_value=selected),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
        ):
            self.assertIsNone(
                evaluate_request(
                    dict(self.event, turn_id="selected", model="gpt-6.1-sol")
                )
            )
        self.assertFalse(RECOMMENDATION_STORE.pending_path("thread").exists())

    def test_unreadable_or_damaged_manual_evidence_is_not_absence(self):
        evidence = RECOMMENDATION_STORE.pending_path("thread")
        evidence.parent.mkdir(parents=True)
        for value in [
            "invalid",
            '{"prompt_hash":"x","active_profile":{},"result":{"decision":"recommend_stronger"}}',
        ]:
            evidence.write_text(value)
            self.assertIn(
                "continue the original task",
                self.invoke(self.error())["systemMessage"].casefold(),
            )
            self.assertEqual(evidence.read_text(), value)
        evidence.unlink()
        evidence.symlink_to(evidence.parent / "missing")
        self.assertIn(
            "continue the original task",
            self.invoke(self.error())["systemMessage"].casefold(),
        )
        self.assertTrue(evidence.is_symlink())

    def test_proven_native_effort_change_can_clear_evidence_without_guessing_from_model(
        self,
    ):
        self.stage_manual_block()
        selected = {
            "task": self.event["prompt"],
            "active_profile": {
                "model": "gpt-6-luna",
                "effort": "medium",
                "speed": None,
            },
        }
        with (
            patch.object(operations, "session_input", return_value=selected),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
        ):
            self.assertIsNone(evaluate_request(dict(self.event, turn_id="selected")))
        self.assertFalse(RECOMMENDATION_STORE.pending_path("thread").exists())

    def test_fresh_unknown_releases_applicable_manual_recommendation(self):
        request = self.stage_manual_block()
        with (
            patch.object(operations, "session_input", return_value=request),
            patch.object(operations, "triage", return_value={"decision": "unknown"}),
        ):
            output = evaluate_request(dict(self.event, turn_id="second"))
        self.assertNotEqual(output.get("decision"), "block")
        self.assertFalse(RECOMMENDATION_STORE.pending_path("thread").exists())
        self.assertEqual(
            HANDOFF_STATE.read_state(HANDOFF_STATE.state_path("thread"))[
                "assessment_decision"
            ],
            "unknown",
        )

    def test_authoritative_keep_clears_only_superseded_applicable_cache(self):
        request = self.stage_manual_block()
        with (
            patch.object(operations, "session_input", return_value=request),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
        ):
            self.assertIsNone(evaluate_request(dict(self.event, turn_id="second")))
        self.assertFalse(RECOMMENDATION_STORE.pending_path("thread").exists())
        self.assertIn(
            "systemMessage",
            self.invoke(self.error(), dict(self.event, turn_id="third")),
        )

    def test_unrelated_keep_does_not_clear_other_work_recommendation(self):
        self.stage_manual_block()
        before = RECOMMENDATION_STORE.pending_path("thread").read_bytes()
        request = {
            "task": "different work",
            "active_profile": {"model": "gpt-6-luna", "effort": "low", "speed": None},
        }
        with (
            patch.object(operations, "session_input", return_value=request),
            patch.object(operations, "triage", return_value={"decision": "keep"}),
        ):
            self.assertIsNone(
                evaluate_request(
                    dict(self.event, turn_id="second", prompt="different work")
                )
            )
        self.assertEqual(
            RECOMMENDATION_STORE.pending_path("thread").read_bytes(), before
        )

    def test_concurrent_recommendation_change_is_not_cleared_by_stale_keep(self):
        request = self.stage_manual_block()

        def keep(_):
            with operations.FileStore().transaction("thread"):
                operations.Assessment().save(
                    "thread", {**request, "task": "another work"}, self.recommendation()
                )
            return {"decision": "keep"}

        operations.submit_prompt(dict(self.event, turn_id="second"))
        output = io.StringIO()
        with (
            patch("sys.argv", ["desktop.py"]),
            patch(
                "sys.stdin", io.StringIO(json.dumps(dict(self.event, turn_id="second")))
            ),
            patch.object(operations, "session_input", return_value=request),
            patch.object(operations, "triage", side_effect=keep),
            patch.object(
                operations,
                "AppServerReader",
                return_value=self.accepted_reader(),
            ),
            redirect_stdout(output),
        ):
            CLI.assess_current()
        self.assertIn(
            "continue the original task",
            json.loads(output.getvalue())["systemMessage"].casefold(),
        )
        self.assertEqual(
            RECOMMENDATION_STORE.load_pending(
                RECOMMENDATION_STORE.pending_path("thread")
            )["prompt_hash"],
            HANDOFF_INPUT.prompt_digest("another work"),
        )
        self.assertEqual(
            HANDOFF_STATE.read_state(HANDOFF_STATE.state_path("thread"))[
                "assessment_decision"
            ],
            "unknown",
        )

    def test_fresh_triage_preserves_real_concurrent_ready_and_attempting_snapshots(
        self,
    ):
        for phase in ["ready", "attempting"]:
            for decision in ["keep", "unknown", "recommend_stronger"]:
                with self.subTest(phase=phase, decision=decision):
                    HANDOFF_STATE.state_path("thread").unlink(missing_ok=True)
                    RECOMMENDATION_STORE.pending_path("thread").unlink(missing_ok=True)
                    state = {
                        "phase": phase,
                        "source_turn_id": "concurrent",
                        "sentinel": "preserved",
                    }

                    def triage(_):
                        write_concurrent_state("thread", state)
                        return (
                            self.recommendation()
                            if decision == "recommend_stronger"
                            else {"decision": decision}
                        )

                    request = {
                        "task": self.event["prompt"],
                        "active_profile": {
                            "model": "gpt-6-luna",
                            "effort": "low",
                            "speed": None,
                        },
                    }
                    with (
                        patch.object(
                            operations,
                            "session_input",
                            return_value=request,
                        ),
                        patch.object(operations, "triage", side_effect=triage),
                        patch.object(operations, "queued_ids", return_value=set()),
                        patch.object(operations, "AppServerReader"),
                    ):
                        result = evaluate_request(self.event)
                    self.assertEqual(result["decision"], "block")
                    self.assertEqual(
                        HANDOFF_STATE.read_state(HANDOFF_STATE.state_path("thread")),
                        state,
                    )
