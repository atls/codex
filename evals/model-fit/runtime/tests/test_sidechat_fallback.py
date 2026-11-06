"""Exact capability fallback and protected handoff regression checks."""

import sys
from pathlib import Path

sys.path.insert(
    0, str((Path(__file__).resolve().parents[4] / "plugins/model-fit") / "src")
)

import io
import json
import os
import select
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import model_fit.entrypoints.desktop.configuration as DESKTOP_CONFIGURATION
import model_fit.entrypoints.desktop.instructions as HOOKS_INSTRUCTIONS
import model_fit.infrastructure.codex.input.codec as HANDOFF_INPUT
import model_fit.infrastructure.codex.transport.connection as CODEX_CONNECTION
import model_fit.infrastructure.handoff.recommendations.files as RECOMMENDATION_STORE
import model_fit.infrastructure.handoff.state.files as HANDOFF_STATE
from model_fit import api as HANDOFF_GUARDS
from model_fit import api as HANDOFF_PREPARATION
from model_fit import api as HANDOFF_RECOMMENDATION
from model_fit.entrypoints.desktop import lifecycle as CLI


class SidechatFallbackTests(unittest.TestCase):
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "thread",
        "turn_id": "turn",
        "cwd": "/fixture",
        "model": "gpt-6-luna",
        "prompt": "ordinary request",
    }

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        environment = patch.dict(
            os.environ,
            {
                "CODEX_HOME": self.temporary.name,
                "CODEX_THREAD_ID": "thread",
                DESKTOP_CONFIGURATION.AUTO_THREAD_ENV: "thread",
            },
        )
        environment.start()
        self.addCleanup(environment.stop)

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
            patch.object(HANDOFF_PREPARATION, "session_input", side_effect=error),
            patch.object(HANDOFF_PREPARATION, "triage") as triage,
            patch.object(HANDOFF_PREPARATION, "AppServerReader") as reader,
        ):
            with redirect_stdout(submitted):
                self.assertEqual(CLI.handle_lifecycle(), 0)
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
        self.assertIn("пригодность не установлена", output["systemMessage"])
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
            HANDOFF_GUARDS.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )
        rows = [
            json.loads(line)
            for line in (
                Path(self.temporary.name) / ".tmp/model-fit-hook-audit/thread.jsonl"
            )
            .read_text()
            .splitlines()
        ]
        self.assertEqual(
            rows[-2]["details"]["reason_code"], "session_thread_not_loaded"
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
                self.assertIn("Продолжай исходную задачу", output["systemMessage"])
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

    def test_pending_and_unknown_attempt_states_remain_protected(
        self,
    ):
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
                    self.assertIn("Продолжай исходную задачу", output["systemMessage"])
                    self.assertEqual(HANDOFF_STATE.read_state(path)["phase"], "passed")
                    continue
                else:
                    self.assertEqual(output["status"], "failed")
                    self.assertEqual(
                        {key: HANDOFF_STATE.read_state(path)[key] for key in state},
                        state,
                    )
                self.assertEqual(
                    HANDOFF_GUARDS.guard_tool(
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
                    "устарела",
                    self.invoke(unavailable)["hookSpecificOutput"]["additionalContext"],
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
        script = "import sys; sys.path.insert(0, sys.argv[1]); from model_fit.infrastructure.handoff.state.files import locked_state\nwith locked_state('thread'):\n print('locked',flush=True)\n sys.stdin.readline()"
        holder = None

        def unavailable(_):
            nonlocal holder
            holder = subprocess.Popen(
                [sys.executable, "-c", script, str(SCRIPTS.parent / "src")],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertTrue(select.select([holder.stdout], [], [], 3)[0])
            self.assertEqual(holder.stdout.readline().strip(), "locked")
            raise self.error()

        try:
            self.assertEqual(self.invoke(unavailable)["status"], "failed")
            self.assertEqual(
                HANDOFF_STATE.read_state(HANDOFF_STATE.state_path("thread"))[
                    "pending_assessment"
                ]["status"],
                "running",
            )
        finally:
            if holder:
                holder.communicate("release\n", timeout=3)

    def test_same_capability_error_from_triage_is_not_session_input_fallback(self):
        HANDOFF_PREPARATION.submit_prompt(self.event)
        output = io.StringIO()
        with (
            patch("sys.argv", ["desktop.py"]),
            patch("sys.stdin", io.StringIO(json.dumps(self.event))),
            patch.object(
                HANDOFF_PREPARATION,
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
            patch.object(HANDOFF_PREPARATION, "triage", side_effect=self.error()),
            patch.object(
                HANDOFF_PREPARATION,
                "AppServerReader",
                return_value=self.accepted_reader(),
            ),
            redirect_stdout(output),
        ):
            CLI.assess_current()
        self.assertIn(
            "Продолжай исходную задачу", json.loads(output.getvalue())["systemMessage"]
        )

    def test_preserved_profile_choice_context_is_not_a_fresh_fallback(self):
        state = {
            "phase": "passed",
            "source_turn_id": "previous",
            "profile_context_turn_id": "choice",
        }
        path = self.write(state)
        self.assertIn(
            "Продолжай исходную задачу", self.invoke(self.error())["systemMessage"]
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
        original = json.loads(json.dumps(event))
        output = self.invoke(self.error(), event)
        self.assertEqual(set(output), {"systemMessage"})
        self.assertEqual(event, original)
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
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=request),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value=self.recommendation()
            ),
            patch.object(
                HANDOFF_PREPARATION,
                "AppServerReader",
                side_effect=RuntimeError("queue unavailable"),
            ),
        ):
            result = HANDOFF_PREPARATION.prepare_handoff(event)
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
        self.assertIn("пригодность не установлена", output["systemMessage"])
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
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=selected),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
        ):
            self.assertIsNone(
                HANDOFF_PREPARATION.prepare_handoff(
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
                "Продолжай исходную задачу", self.invoke(self.error())["systemMessage"]
            )
            self.assertEqual(evidence.read_text(), value)
        evidence.unlink()
        evidence.symlink_to(evidence.parent / "missing")
        self.assertIn(
            "Продолжай исходную задачу", self.invoke(self.error())["systemMessage"]
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
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=selected),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
        ):
            self.assertIsNone(
                HANDOFF_PREPARATION.prepare_handoff(
                    dict(self.event, turn_id="selected")
                )
            )
        self.assertFalse(RECOMMENDATION_STORE.pending_path("thread").exists())

    def test_fresh_unknown_releases_applicable_manual_recommendation(self):
        request = self.stage_manual_block()
        with (
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=request),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "unknown"}
            ),
        ):
            output = HANDOFF_PREPARATION.prepare_handoff(
                dict(self.event, turn_id="second")
            )
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
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=request),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
        ):
            self.assertIsNone(
                HANDOFF_PREPARATION.prepare_handoff(dict(self.event, turn_id="second"))
            )
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
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=request),
            patch.object(
                HANDOFF_PREPARATION, "triage", return_value={"decision": "keep"}
            ),
        ):
            self.assertIsNone(
                HANDOFF_PREPARATION.prepare_handoff(
                    dict(self.event, turn_id="second", prompt="different work")
                )
            )
        self.assertEqual(
            RECOMMENDATION_STORE.pending_path("thread").read_bytes(), before
        )

    def test_concurrent_recommendation_change_is_not_cleared_by_stale_keep(self):
        request = self.stage_manual_block()

        def keep(_):
            dependencies = HANDOFF_RECOMMENDATION._handoff_dependencies()
            with dependencies.state.transaction("thread"):
                dependencies.cache.save(
                    "thread", {**request, "task": "another work"}, self.recommendation()
                )
            return {"decision": "keep"}

        HANDOFF_PREPARATION.submit_prompt(dict(self.event, turn_id="second"))
        output = io.StringIO()
        with (
            patch("sys.argv", ["desktop.py"]),
            patch(
                "sys.stdin", io.StringIO(json.dumps(dict(self.event, turn_id="second")))
            ),
            patch.object(HANDOFF_PREPARATION, "session_input", return_value=request),
            patch.object(HANDOFF_PREPARATION, "triage", side_effect=keep),
            patch.object(
                HANDOFF_PREPARATION,
                "AppServerReader",
                return_value=self.accepted_reader(),
            ),
            redirect_stdout(output),
        ):
            CLI.assess_current()
        self.assertIn(
            "Продолжай исходную задачу", json.loads(output.getvalue())["systemMessage"]
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
                    holder = None
                    state = {
                        "phase": phase,
                        "source_turn_id": "concurrent",
                        "sentinel": "preserved",
                    }
                    script = "import json,sys; sys.path.insert(0,sys.argv[1]); from model_fit.infrastructure.handoff.state.files import locked_state,write_state\nwith locked_state('thread') as path: write_state(path,json.loads(sys.argv[2]))\nprint('written',flush=True)\nsys.stdin.readline()"

                    def triage(_):
                        nonlocal holder
                        holder = subprocess.Popen(
                            [
                                sys.executable,
                                "-c",
                                script,
                                str(SCRIPTS.parent / "src"),
                                json.dumps(state),
                            ],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                        )
                        self.assertTrue(select.select([holder.stdout], [], [], 3)[0])
                        self.assertEqual(holder.stdout.readline().strip(), "written")
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
                    try:
                        with (
                            patch.object(
                                HANDOFF_PREPARATION,
                                "session_input",
                                return_value=request,
                            ),
                            patch.object(
                                HANDOFF_PREPARATION, "triage", side_effect=triage
                            ),
                            patch.object(
                                HANDOFF_PREPARATION, "queued_ids", return_value=set()
                            ),
                            patch.object(HANDOFF_PREPARATION, "AppServerReader"),
                        ):
                            result = HANDOFF_PREPARATION.prepare_handoff(self.event)
                        self.assertEqual(result["decision"], "block")
                        self.assertEqual(
                            HANDOFF_STATE.read_state(
                                HANDOFF_STATE.state_path("thread")
                            ),
                            state,
                        )
                    finally:
                        if holder:
                            holder.communicate("release\n", timeout=3)
