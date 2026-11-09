import copy
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import model_fit.entrypoints.hooks.operations as api
from model_fit.autoswitch.exceptions.unavailable import SubmissionUnavailable
from model_fit.entrypoints.hooks.instructions import (
    CONTROL_PROMPT,
    assessment_command,
    pending_context,
    queue_command,
)
from model_fit.entrypoints.hooks.presentation import HookPresentation
from model_fit.infrastructure.adapters.codex.codec import input_digest
from model_fit.infrastructure.adapters.codex.transport.connection import (
    AppServerRPCError,
)
from model_fit.infrastructure.adapters.filesystem.recommendations import (
    FileRecommendations,
)
from model_fit.infrastructure.adapters.filesystem.state import (
    locked_state,
    read_state,
    state_path,
    write_state,
)


class SubmittedInputTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.env = patch.dict(
            os.environ,
            {"CODEX_HOME": self.home.name, "CODEX_THREAD_ID": "submitted-thread"},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.content = [
            {
                "type": "text",
                "text": "Inspect both",
                "text_elements": [
                    {"byteRange": {"start": 0, "end": 7}, "placeholder": "annotation"}
                ],
            },
            {"type": "image", "url": "fixture-a", "detail": None},
            {"type": "image", "url": "fixture-b", "detail": "original"},
        ]
        self.event = {
            "session_id": "submitted-thread",
            "turn_id": "source-turn",
            "cwd": "/tmp",
            "model": "gpt-6-luna",
            "prompt": "Inspect both",
        }
        self.profile = {"model": "gpt-6-luna", "effort": "low", "speed": None}
        self.reader = MagicMock()
        self.reader.__enter__.return_value.call.side_effect = self.rpc
        self.received = []
        self.message_client = "composer-client"
        self.consumed_content = self.content
        self.pending_queue = []
        self.steering = []

    def rpc(self, method, params, timeout):
        if method == "thread/queue/list":
            return {
                "data": [{"id": ident} for ident in self.pending_queue],
                "nextCursor": None,
            }
        if method == "thread/items/list":
            content = (
                self.content
                if params["turnId"] == "source-turn"
                else self.consumed_content
            )
            messages = [
                {
                    "item": {
                        "type": "userMessage",
                        "id": "accepted-message",
                        "clientId": self.message_client,
                        "content": content,
                    }
                }
            ]
            if params["turnId"] == "source-turn" and self.steering:
                messages.append(
                    {
                        "item": {
                            "type": "userMessage",
                            "id": "steering-message",
                            "content": self.steering,
                        }
                    }
                )
            return {"data": messages, "nextCursor": None}
        if method == "thread/read":
            return {
                "thread": {
                    "model": self.profile["model"],
                    "reasoningEffort": self.profile["effort"],
                    "parentThreadId": None,
                }
            }
        if method == "thread/queue/add":
            self.received.append(copy.deepcopy(params["input"]))
            return {
                "queuedSubmission": {
                    "id": "native-receipt",
                    "input": copy.deepcopy(params["input"]),
                    "clientUserMessageId": params["clientUserMessageId"],
                }
            }
        raise AssertionError(method)

    def assess(self, event=None, decision=None):
        return api.assess_submitted(
            context_reader=lambda e: {
                "task": e["prompt"] or "attachments",
                "active_profile": self.profile,
            },
            assessor=decision or (lambda request: {"decision": "keep"}),
            native_factory=lambda cwd: self.reader,
        )

    def test_submit_defers_lookup_then_assesses_complete_native_body(self):
        with patch.object(
            api, "session_input", side_effect=AssertionError("input not accepted yet")
        ):
            result = api.submit_prompt(self.event)
        self.assertEqual(result, pending_context())
        state = read_state(state_path("submitted-thread"))
        self.assertNotIn("Inspect both", str(state))
        denied = api.guard_tool(
            {
                **self.event,
                "tool_name": "Bash",
                "tool_input": {"command": "touch forbidden"},
            }
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        audit_text = (
            state_path("submitted-thread").parents[1]
            / "model-fit-hook-audit/submitted-thread.jsonl"
        ).read_text()
        denial = json.loads(audit_text.splitlines()[-1])
        self.assertEqual(denial["details"]["reason_code"], "assessment_pending")
        self.assertEqual(denial["executor_thread_id"], "submitted-thread")
        self.assertEqual(denial["turn_id"], "source-turn")
        self.assertNotIn("touch forbidden", audit_text)
        self.assertNotIn("Inspect both", audit_text)
        self.assertIsNone(
            api.guard_tool(
                {
                    **self.event,
                    "tool_name": "Bash",
                    "tool_input": {"command": assessment_command()},
                }
            )
        )
        observed = []
        output = self.assess(
            decision=lambda request: (
                observed.append(request["input"]) or {"decision": "keep"}
            )
        )
        self.assertEqual(observed, [self.content])
        self.assertIn(
            "already assessed",
            output["hookSpecificOutput"]["additionalContext"].casefold(),
        )
        self.assertIsNone(
            api.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )
        self.assertEqual(read_state(state_path("submitted-thread"))["phase"], "passed")

    def test_changed_requirements_reassess_original_native_input(self):
        api.submit_prompt(self.event)
        self.assess()
        seen = []
        self.reader.__enter__.return_value.call.side_effect = (
            lambda method, params, timeout: (
                {"data": [{"id": "source-turn"}], "nextCursor": None}
                if method == "thread/turns/list"
                else self.rpc(method, params, timeout)
            )
        )
        api.reassess(
            "Discovered requirement: durable jobs and idempotent writes",
            context_reader=lambda _: {
                "task": "Inspect both",
                "active_profile": self.profile,
            },
            assessor=lambda request: seen.append(request) or {"decision": "keep"},
            native_factory=lambda _: self.reader,
        )
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["input"], self.content)
        self.assertIn("durable jobs", seen[0]["context"])
        self.assertEqual(read_state(state_path("submitted-thread"))["phase"], "passed")
        self.assertEqual(self.received, [])

    def test_reassessment_keeps_new_requirements_when_history_fills_context(self):
        from model_fit.assessment.validation import validated_request

        api.submit_prompt(self.event)
        self.assess()
        self.reader.__enter__.return_value.call.side_effect = (
            lambda method, params, timeout: (
                {"data": [{"id": "source-turn"}], "nextCursor": None}
                if method == "thread/turns/list"
                else self.rpc(method, params, timeout)
            )
        )
        seen = []
        requirements = "new requirement; " * 200

        def evaluate(request):
            validated_request(request)
            seen.append(request)
            return {"decision": "keep"}

        api.reassess(
            requirements,
            context_reader=lambda _: {
                "task": "Inspect both",
                "active_profile": self.profile,
                "context": "h" * 18000,
            },
            assessor=evaluate,
            native_factory=lambda _: self.reader,
        )
        self.assertEqual(len(seen), 1)
        self.assertIn(requirements, seen[0]["context"])
        self.assertLessEqual(len(seen[0]["context"]), 20000)
        self.assertEqual(seen[0]["input"], self.content)

    def test_oversized_reassessment_requirements_leave_submission_unchanged(self):
        api.submit_prompt(self.event)
        self.assess()
        before = state_path("submitted-thread").read_bytes()
        with self.assertRaises(ValueError):
            api.reassess("r" * 20000, native_factory=lambda _: self.reader)
        self.assertEqual(state_path("submitted-thread").read_bytes(), before)

    def test_reassessment_rejects_foreign_turn_and_unresolved_state(self):
        api.submit_prompt(self.event)
        with self.assertRaises(SubmissionUnavailable):
            api.reassess("new facts", native_factory=lambda _: self.reader)
        self.assess()
        before = state_path("submitted-thread").read_bytes()
        self.reader.__enter__.return_value.call.side_effect = (
            lambda method, params, timeout: (
                {"data": [{"id": "different-turn"}], "nextCursor": None}
                if method == "thread/turns/list"
                else self.rpc(method, params, timeout)
            )
        )
        with self.assertRaises(SubmissionUnavailable):
            api.reassess("new facts", native_factory=lambda _: self.reader)
        self.assertEqual(state_path("submitted-thread").read_bytes(), before)
        self.assertEqual(self.received, [])

    def test_new_submission_supersedes_requirements_reassessment(self):
        api.submit_prompt(self.event)
        self.assess()
        self.reader.__enter__.return_value.call.side_effect = (
            lambda method, params, timeout: (
                {"data": [{"id": "source-turn"}], "nextCursor": None}
                if method == "thread/turns/list"
                else self.rpc(method, params, timeout)
            )
        )

        def evaluate(request):
            api.submit_prompt(
                {**self.event, "turn_id": "new-turn", "prompt": "new request"}
            )
            return {"decision": "keep"}

        api.reassess(
            "new facts",
            context_reader=lambda _: {
                "task": "Inspect both",
                "active_profile": self.profile,
            },
            assessor=evaluate,
            native_factory=lambda _: self.reader,
        )
        state = read_state(state_path("submitted-thread"))
        self.assertEqual(state["pending_assessment"]["turn_id"], "new-turn")
        self.assertEqual(state["pending_assessment"]["status"], "waiting")

    def test_reassessment_can_recommend_and_queue_preserving_attachments(self):
        api.submit_prompt(self.event)
        self.assess()

        def rpc(method, params, timeout):
            if method == "thread/turns/list":
                return {"data": [{"id": "source-turn"}], "nextCursor": None}
            return self.rpc(method, params, timeout)

        self.reader.__enter__.return_value.call.side_effect = rpc
        result = {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "active_speed": None,
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "high",
            "recommended_speed": None,
            "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
            "official_guidance": "fixture",
            "task_inference": "fixture",
        }
        api.reassess(
            "New requirements from issue",
            context_reader=lambda _: {
                "task": "Inspect both",
                "active_profile": self.profile,
            },
            assessor=lambda _: result,
            native_factory=lambda _: self.reader,
        )
        self.assertEqual(read_state(state_path("submitted-thread"))["phase"], "ready")
        self.profile = {"model": "gpt-6.1-sol", "effort": "high", "speed": None}
        api.enqueue_handoff(
            "submitted-thread", "source-turn", native_factory=lambda _: self.reader
        )
        self.assertEqual(self.received, [self.content])

    def test_reassessment_of_bound_replay_preserves_current_native_choice(self):
        self.stage_and_queue()
        api.submit_prompt({**self.event, "turn_id": "replay", "model": "gpt-6.1-sol"})
        self.assess()
        self.profile = {"model": "gpt-6.1-terra", "effort": "medium", "speed": None}

        def rpc(method, params, timeout):
            if method == "thread/turns/list":
                return {"data": [{"id": "replay"}], "nextCursor": None}
            return self.rpc(method, params, timeout)

        self.reader.__enter__.return_value.call.side_effect = rpc
        observed = []
        api.reassess(
            "New requirements from issue",
            context_reader=lambda _: {
                "task": "Inspect both",
                "active_profile": self.profile,
            },
            assessor=lambda request: observed.append(request) or {"decision": "keep"},
            native_factory=lambda _: self.reader,
        )
        self.assertEqual(observed[0]["active_profile"], self.profile)
        self.assertEqual(observed[0]["input"], self.content)
        self.assertEqual(len(self.received), 1)
        self.assertEqual(
            read_state(state_path("submitted-thread"))["source_turn_id"], "replay"
        )

    def test_reassessment_child_does_not_become_root_or_modify_parent(self):
        parent = state_path("parent-thread")
        parent.parent.mkdir(parents=True, exist_ok=True)
        write_state(parent, {"phase": "passed", "source_turn_id": "parent-turn"})
        original = parent.read_bytes()
        api.submit_prompt(self.event)
        self.assess()

        def rpc(method, params, timeout):
            if method == "thread/turns/list":
                return {"data": [{"id": "source-turn"}], "nextCursor": None}
            result = self.rpc(method, params, timeout)
            if method == "thread/read":
                result["thread"]["parentThreadId"] = "parent-thread"
            return result

        self.reader.__enter__.return_value.call.side_effect = rpc
        result = {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "active_speed": None,
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "high",
            "recommended_speed": None,
            "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
            "official_guidance": "fixture",
            "task_inference": "fixture",
        }
        api.reassess(
            "new requirements",
            context_reader=lambda _: {
                "task": "Inspect both",
                "active_profile": self.profile,
            },
            assessor=lambda _: result,
            native_factory=lambda _: self.reader,
        )
        self.assertEqual(parent.read_bytes(), original)
        self.assertNotEqual(
            read_state(state_path("submitted-thread"))["phase"], "ready"
        )
        self.assertEqual(self.received, [])

    def test_native_manual_choice_after_keep_is_presented_to_assessor(self):
        for profile in (
            {"model": "gpt-6.1-terra", "effort": "medium", "speed": None},
            {"model": "gpt-6-luna", "effort": "high", "speed": None},
        ):
            with (
                self.subTest(profile=profile),
                tempfile.TemporaryDirectory() as home,
                patch.dict(os.environ, {"CODEX_HOME": home}),
            ):
                self.profile = {"model": "gpt-6-luna", "effort": "low", "speed": None}
                api.submit_prompt(self.event)
                self.assess()
                self.profile = profile
                api.submit_prompt(
                    {
                        **self.event,
                        "turn_id": "followup",
                        "model": self.profile["model"],
                        "prompt": "Read login",
                    }
                )
                seen = []
                self.assess(
                    decision=lambda request: (
                        seen.append(request) or {"decision": "keep"}
                    )
                )
                self.assertIn(
                    "retained native chat owner", seen[0].get("context", "").casefold()
                )
                self.assertEqual(
                    read_state(state_path("submitted-thread"))["native_profile"],
                    self.profile,
                )
                self.assertEqual(self.received, [])

    def test_native_choice_during_assessment_cancels_obsolete_recommendation(self):
        api.submit_prompt(self.event)

        def evaluate(request):
            self.profile = {"model": "gpt-6.1-terra", "effort": "medium", "speed": None}
            return {
                "decision": "recommend_stronger",
                "active_model": "gpt-6-luna",
                "active_effort": "low",
                "active_speed": None,
                "recommended_model": "gpt-6.1-sol",
                "recommended_effort": "high",
                "recommended_speed": None,
                "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
                "official_guidance": "fixture",
                "task_inference": "fixture",
            }

        output = self.assess(decision=evaluate)
        state = read_state(state_path("submitted-thread"))
        self.assertEqual(state["phase"], "passed")
        self.assertEqual(state["native_profile"], self.profile)
        self.assertEqual(state["assessment_decision"], "native_override")
        self.assertNotIn(
            "profile change",
            output.get("hookSpecificOutput", {}).get("additionalContext", ""),
        )
        self.assertEqual(self.received, [])

    def test_assessor_timeout_continues_without_claiming_fit_or_leaking_error(self):
        api.submit_prompt(self.event)

        def unavailable(request):
            raise subprocess.TimeoutExpired(["private-exception-sentinel"], 1)

        output = self.assess(decision=unavailable)
        self.assertIn("continue the original task", output["systemMessage"].casefold())
        self.assertIn("suitability is unknown", output["systemMessage"].casefold())
        self.assertIsNone(
            api.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )
        self.assertEqual(self.received, [])
        state = read_state(state_path("submitted-thread"))
        self.assertEqual(state["assessment_decision"], "unknown")
        audit = (
            state_path("submitted-thread").parents[1]
            / "model-fit-hook-audit/submitted-thread.jsonl"
        ).read_text()
        self.assertIn("auto_assessment_error:TimeoutExpired", audit)
        self.assertIn("failure_line", audit)
        self.assertNotIn("private-exception-sentinel", audit + str(output))

    def test_failed_assessment_allows_work_but_not_transfer_or_foreign_turn(self):
        for phase in ("submitted", "passed", "ready", "attempting", "queued"):
            with self.subTest(phase=phase):
                path = state_path("submitted-thread")
                path.unlink(missing_ok=True)
                api.submit_prompt(self.event)
                state = read_state(path)
                state["phase"] = phase
                state["pending_assessment"].update(
                    status="failed", failure_reason="assessment_failed"
                )
                write_state(path, state)
                ordinary = api.guard_tool(
                    {
                        **self.event,
                        "tool_name": "Bash",
                        "tool_input": {"command": "pwd"},
                    }
                )
                admitted = api.can_continue_admitted_tool(
                    {
                        **self.event,
                        "tool_name": "Bash",
                        "tool_input": {"command": "pwd"},
                    }
                )
                if phase in {"submitted", "passed", "ready"}:
                    self.assertIsNone(ordinary)
                    self.assertTrue(admitted)
                else:
                    self.assertFalse(admitted)
                    self.assertEqual(
                        ordinary["hookSpecificOutput"]["permissionDecision"], "deny"
                    )
                for turn, command in (
                    ("foreign", "pwd"),
                    ("source-turn", queue_command("current", "source")),
                ):
                    denial = api.guard_tool(
                        {
                            **self.event,
                            "turn_id": turn,
                            "tool_name": "Bash",
                            "tool_input": {"command": command},
                        }
                    )
                    self.assertEqual(
                        denial["hookSpecificOutput"]["permissionDecision"], "deny"
                    )

    def test_a_control_message_cannot_replace_unassessed_native_input(self):
        api.submit_prompt(self.event)
        path = state_path("submitted-thread")
        saved = path.read_bytes()
        output = api.submit_prompt(
            {**self.event, "turn_id": "control", "prompt": CONTROL_PROMPT}
        )
        self.assertEqual(output["decision"], "block")
        self.assertEqual(path.read_bytes(), saved)
        observed = []
        self.assess(
            decision=lambda request: (
                observed.append(request["input"]) or {"decision": "keep"}
            )
        )
        self.assertEqual(observed, [self.content])

    def test_native_retry_without_new_user_input_releases_only_stale_pending(self):
        api.submit_prompt(self.event)
        path = state_path("submitted-thread")
        state = read_state(path)
        state["phase"] = "passed"
        state["profile_context_turn_id"] = "manual-choice"
        state["native_profile"] = self.profile
        write_state(path, state)

        def retry_rpc(method, params, timeout):
            if method == "thread/turns/list":
                return {
                    "data": [
                        {"id": "retry-turn", "startedAt": 3, "status": "inProgress"},
                        {"id": "source-turn", "completedAt": 2, "status": "failed"},
                    ],
                    "nextCursor": None,
                }
            if method == "thread/items/list" and params["turnId"] == "retry-turn":
                return {"data": [], "nextCursor": None}
            return self.rpc(method, params, timeout)

        self.reader.__enter__.return_value.call.side_effect = retry_rpc
        retry = {
            **self.event,
            "turn_id": "retry-turn",
            "tool_name": "Bash",
            "tool_input": {"command": assessment_command()},
        }
        with patch.object(api, "AppServerReader", return_value=self.reader):
            self.assertIsNone(api.guard_tool(retry))
        saved = read_state(path)
        self.assertEqual(saved["source_turn_id"], "retry-turn")
        self.assertEqual(saved["assessment_decision"], "unknown")
        self.assertNotIn("pending_assessment", saved)
        self.assertNotEqual(
            saved["assessment_generation"], state["pending_assessment"]["generation"]
        )
        self.assertEqual(saved["native_profile"], self.profile)
        self.assertEqual(saved["profile_context_turn_id"], "manual-choice")
        output = api.assess_submitted(
            context_reader=lambda _: self.fail("stale input was read"),
            assessor=lambda _: self.fail("stale input was assessed"),
        )
        self.assertIn("suitability is unknown", output["systemMessage"].casefold())
        self.assertIsNone(api.guard_tool({**retry, "tool_input": {"command": "pwd"}}))
        self.assertEqual(self.received, [])

    def test_retry_cannot_retire_live_newer_or_unread_submission(self):
        api.submit_prompt(self.event)
        path = state_path("submitted-thread")
        saved = path.read_bytes()
        source = {"id": "source-turn", "completedAt": 2, "status": "failed"}
        current = {"id": "retry-turn", "startedAt": 3, "status": "inProgress"}
        retry = {
            **self.event,
            "turn_id": "retry-turn",
            "tool_name": "Bash",
            "tool_input": {"command": assessment_command()},
        }
        for case in (
            "newer_turn",
            "source_running",
            "missing_time",
            "new_user_later_page",
            "repeated_cursor",
            "rpc_failure",
            "blocking_recommendation",
        ):
            if case == "blocking_recommendation":
                FileRecommendations().save(
                    "submitted-thread",
                    {"task": "Inspect both", "active_profile": self.profile},
                    {
                        "decision": "recommend_stronger",
                        "active_model": "gpt-6-luna",
                        "active_effort": "low",
                        "active_speed": None,
                        "recommended_model": "gpt-6.1-sol",
                        "recommended_effort": "high",
                        "recommended_speed": None,
                        "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
                        "official_guidance": "fixture",
                        "task_inference": "fixture",
                    },
                )

            def retry_rpc(method, params, timeout, *, case=case):
                if case == "rpc_failure":
                    raise RuntimeError("fixture unavailable")
                if method == "thread/turns/list":
                    before = (
                        {**source, "status": "inProgress"}
                        if case == "source_running"
                        else source
                    )
                    after = (
                        {**current, "id": "newer-turn"}
                        if case == "newer_turn"
                        else current
                    )
                    if case == "missing_time":
                        before = {**before, "completedAt": None}
                    return {"data": [after, before], "nextCursor": None}
                if method == "thread/items/list":
                    if case == "blocking_recommendation":
                        return {"data": [], "nextCursor": None}
                    if case == "new_user_later_page" and params.get("cursor"):
                        return {
                            "data": [
                                {
                                    "item": {
                                        "type": "userMessage",
                                        "content": self.content,
                                    }
                                }
                            ],
                            "nextCursor": None,
                        }
                    return {"data": [], "nextCursor": "next-page"}
                return self.rpc(method, params, timeout)

            self.reader.__enter__.return_value.call.side_effect = retry_rpc
            with (
                self.subTest(case=case),
                patch.object(api, "AppServerReader", return_value=self.reader),
            ):
                output = api.guard_tool(retry)
                self.assertEqual(
                    output["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                self.assertEqual(path.read_bytes(), saved)
                if case == "blocking_recommendation":
                    self.assertIsNotNone(FileRecommendations().load("submitted-thread"))

    def test_retry_snapshot_cannot_clear_a_new_generation(self):
        api.submit_prompt(self.event)
        path = state_path("submitted-thread")
        replacement = []

        def retry_rpc(method, params, timeout):
            if method == "thread/turns/list":
                return {
                    "data": [
                        {"id": "retry-turn", "startedAt": 3, "status": "inProgress"},
                        {"id": "source-turn", "completedAt": 2, "status": "failed"},
                    ],
                    "nextCursor": None,
                }
            if method == "thread/items/list":
                api.submit_prompt(
                    {
                        **self.event,
                        "turn_id": "new-turn",
                        "prompt": "New accepted input",
                    }
                )
                replacement.append(path.read_bytes())
                return {"data": [], "nextCursor": None}
            return self.rpc(method, params, timeout)

        self.reader.__enter__.return_value.call.side_effect = retry_rpc
        retry = {
            **self.event,
            "turn_id": "retry-turn",
            "tool_name": "Bash",
            "tool_input": {"command": assessment_command()},
        }
        with patch.object(api, "AppServerReader", return_value=self.reader):
            output = api.guard_tool(retry)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(path.read_bytes(), replacement[0])

    def test_retired_retry_generation_cancels_inflight_assessment_result(self):
        api.submit_prompt(self.event)
        path = state_path("submitted-thread")
        entered, release = (threading.Event(), threading.Event())
        outputs = []

        def assessor(request):
            entered.set()
            self.assertTrue(release.wait(2))
            return {"decision": "keep"}

        worker = threading.Thread(
            target=lambda: outputs.append(self.assess(decision=assessor))
        )
        worker.start()
        try:
            self.assertTrue(entered.wait(2))

            def retry_rpc(method, params, timeout):
                if method == "thread/turns/list":
                    return {
                        "data": [
                            {
                                "id": "retry-turn",
                                "startedAt": 3,
                                "status": "inProgress",
                            },
                            {"id": "source-turn", "completedAt": 2, "status": "failed"},
                        ],
                        "nextCursor": None,
                    }
                if method == "thread/items/list":
                    return {"data": [], "nextCursor": None}
                return self.rpc(method, params, timeout)

            self.reader.__enter__.return_value.call.side_effect = retry_rpc
            retry = {
                **self.event,
                "turn_id": "retry-turn",
                "tool_name": "Bash",
                "tool_input": {"command": assessment_command()},
            }
            with patch.object(api, "AppServerReader", return_value=self.reader):
                self.assertIsNone(api.guard_tool(retry))
            saved = path.read_bytes()
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(path.read_bytes(), saved)
        self.assertIn(
            "superseded",
            outputs[0]["hookSpecificOutput"]["additionalContext"].casefold(),
        )
        self.assertEqual(self.received, [])

    def test_assessment_interpreter_alias_keeps_venv_and_command_constraints(self):
        api.submit_prompt(self.event)
        directory = Path(self.home.name) / "runtime/bin"
        directory.mkdir(parents=True)
        first, second = (directory / "python", directory / "python3")
        first.symlink_to(sys.executable)
        second.symlink_to(sys.executable)
        foreign = Path(self.home.name) / "foreign/bin/python"
        foreign.parent.mkdir(parents=True)
        foreign.symlink_to(sys.executable)
        different = directory / "other"
        different.write_text("not the active interpreter")
        with patch.object(sys, "executable", str(second)):
            command = shlex.join(
                [str(first), "-m", "model_fit.entrypoints.hooks.cli", "assess"]
            )
            self.assertIsNone(
                api.guard_tool(
                    {
                        **self.event,
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    }
                )
            )
            for altered in (
                command + "; touch forbidden",
                command + " extra",
                shlex.join(
                    [str(foreign), "-m", "model_fit.entrypoints.hooks.cli", "assess"]
                ),
                shlex.join(
                    [str(different), "-m", "model_fit.entrypoints.hooks.cli", "assess"]
                ),
                shlex.join([str(first), "-m", "another_module", "assess"]),
                shlex.join([str(first), "-c", "print(1)"]),
            ):
                with self.subTest(command=altered):
                    output = api.guard_tool(
                        {
                            **self.event,
                            "tool_name": "Bash",
                            "tool_input": {"command": altered},
                        }
                    )
                    self.assertEqual(
                        output["hookSpecificOutput"]["permissionDecision"], "deny"
                    )
        self.assertEqual(self.received, [])

    def test_queue_interpreter_alias_is_allowed_once_and_denied_in_replay(self):
        self.assertEqual(
            Path(shlex.split(queue_command("submitted-thread", "source-turn"))[0]).name,
            "python",
        )
        api.submit_prompt(self.event)
        self.assess(
            decision=lambda _: {
                "decision": "recommend_stronger",
                "active_model": "gpt-6-luna",
                "active_effort": "low",
                "active_speed": None,
                "recommended_model": "gpt-6.1-sol",
                "recommended_effort": "high",
                "recommended_speed": None,
                "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
                "official_guidance": "fixture",
                "task_inference": "fixture",
            }
        )
        alias = Path(sys.executable).with_name(
            "python3" if Path(sys.executable).name == "python" else "python"
        )
        self.assertTrue(alias.samefile(sys.executable))
        command = shlex.join(
            [
                str(alias),
                "-m",
                "model_fit.entrypoints.hooks.cli",
                "queue",
                "--thread-id",
                "submitted-thread",
                "--turn-id",
                "source-turn",
            ]
        )
        check = {**self.event, "tool_name": "Bash", "tool_input": {"command": command}}
        self.assertIsNone(api.guard_tool(check))
        self.profile = {"model": "gpt-6.1-sol", "effort": "high", "speed": None}
        api.enqueue_handoff(
            "submitted-thread", "source-turn", native_factory=lambda _: self.reader
        )
        self.message_client = "source-turn"
        self.consumed_content = self.received[0]
        api.submit_prompt(
            {**self.event, "turn_id": "native-replay", "model": "gpt-6.1-sol"}
        )
        self.assess(decision=lambda _: self.fail("Unchanged replay was reassessed"))
        path = state_path("submitted-thread")
        saved = path.read_bytes()
        output = api.guard_tool({**check, "turn_id": "native-replay"})
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(path.read_bytes(), saved)
        self.assertEqual(self.received, [self.content])

    def test_child_submission_and_assessment_do_not_change_parent_state(self):
        for parent_phase in ("passed", "queued"):
            with self.subTest(parent_phase=parent_phase):
                parent_path = state_path("parent-thread")
                parent_path.parent.mkdir(parents=True, exist_ok=True)
                parent = {
                    "phase": parent_phase,
                    "source_turn_id": "parent-source",
                    "replay_turn_id": "parent-turn",
                }
                write_state(parent_path, parent)
                saved_parent = parent_path.read_bytes()
                child_event = {
                    **self.event,
                    "session_id": "parent-thread",
                    "agent_id": "submitted-thread",
                    "agent_type": "default",
                }
                api.submit_prompt(child_event)
                self.assertEqual(parent_path.read_bytes(), saved_parent)
                self.assertEqual(
                    read_state(state_path("submitted-thread"))["pending_assessment"][
                        "turn_id"
                    ],
                    "source-turn",
                )
                output = self.assess()
                self.assertIn(
                    "already assessed",
                    output["hookSpecificOutput"]["additionalContext"].casefold(),
                )
                self.assertEqual(parent_path.read_bytes(), saved_parent)
                self.assertIsNone(
                    api.guard_tool(
                        {
                            "session_id": "parent-thread",
                            "turn_id": "parent-turn",
                            "tool_name": "Bash",
                            "tool_input": {"command": "pwd"},
                        }
                    )
                )

    def test_two_children_have_independent_pending_submissions(self):
        for child in ("first-child", "second-child"):
            api.submit_prompt(
                {
                    **self.event,
                    "session_id": "parent-thread",
                    "agent_id": child,
                    "turn_id": child + "-turn",
                }
            )
        self.assertIsNone(read_state(state_path("parent-thread")))
        for child in ("first-child", "second-child"):
            self.assertEqual(
                read_state(state_path(child))["pending_assessment"]["turn_id"],
                child + "-turn",
            )

    def test_child_assessor_failure_does_not_block_parent_assessment_tool(self):
        parent_path = state_path("parent-thread")
        parent_path.parent.mkdir(parents=True, exist_ok=True)
        write_state(
            parent_path,
            {
                "phase": "passed",
                "source_turn_id": "parent-turn",
                "assessment_decision": "keep",
            },
        )
        saved_parent = parent_path.read_bytes()
        api.submit_prompt(
            {
                **self.event,
                "session_id": "parent-thread",
                "agent_id": "submitted-thread",
            }
        )
        output = self.assess(
            decision=lambda _: (_ for _ in ()).throw(
                RuntimeError("provider fixture failure")
            )
        )
        self.assertIn("continue the original task", output["systemMessage"].casefold())
        self.assertEqual(parent_path.read_bytes(), saved_parent)
        self.assertIsNone(
            api.guard_tool(
                {
                    "session_id": "parent-thread",
                    "turn_id": "parent-turn",
                    "tool_name": "Bash",
                    "tool_input": {"command": assessment_command()},
                }
            )
        )

    def test_child_recommendation_returns_to_allocator_without_automatic_queue(self):
        parent_path = state_path("parent-thread")
        parent_path.parent.mkdir(parents=True, exist_ok=True)
        write_state(parent_path, {"phase": "passed", "source_turn_id": "parent-turn"})
        saved_parent = parent_path.read_bytes()
        api.submit_prompt(
            {
                **self.event,
                "session_id": "parent-thread",
                "agent_id": "submitted-thread",
            }
        )
        output = self.assess(
            decision=lambda _: {
                "decision": "recommend_stronger",
                "active_model": "gpt-6-luna",
                "active_effort": "low",
                "active_speed": None,
                "recommended_model": "gpt-6.1-sol",
                "recommended_effort": "high",
                "recommended_speed": None,
                "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
                "official_guidance": "fixture",
                "task_inference": "fixture",
            }
        )
        self.assertEqual(output["decision"], "block")
        self.assertIn("parent", output["reason"].casefold())
        self.assertEqual(self.received, [])
        self.assertEqual(parent_path.read_bytes(), saved_parent)

    def test_invalid_child_identity_cannot_fall_back_to_parent(self):
        with self.assertRaises(ValueError):
            api.submit_prompt(
                {
                    **self.event,
                    "session_id": "parent-thread",
                    "agent_id": "../parent-thread",
                }
            )
        self.assertIsNone(read_state(state_path("parent-thread")))

    def test_new_input_during_native_read_returns_superseded_without_changing_latest_state(
        self,
    ):
        api.submit_prompt(self.event)
        latest = []

        def read_context(event):
            api.submit_prompt(
                {**self.event, "turn_id": "new-turn", "prompt": "new input"}
            )
            latest.append(read_state(state_path("submitted-thread")))
            return {"task": "old input", "active_profile": self.profile}

        output = api.assess_submitted(
            context_reader=read_context,
            assessor=lambda _: {"decision": "keep"},
            native_factory=lambda _: self.reader,
        )
        self.assertIn(
            "superseded", output["hookSpecificOutput"]["additionalContext"].casefold()
        )
        self.assertEqual(read_state(state_path("submitted-thread")), latest[0])
        self.assertEqual(self.received, [])
        self.assertIsNone(
            api.guard_tool(
                {
                    **self.event,
                    "turn_id": "new-turn",
                    "tool_name": "Bash",
                    "tool_input": {"command": assessment_command()},
                }
            )
        )

    def test_old_assessment_cannot_fail_new_identical_assessment(self):
        path = state_path("submitted-thread")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_state(
            path,
            {
                "phase": "passed",
                "source_turn_id": "previous-turn",
                "assessment_decision": "keep",
            },
        )
        api.submit_prompt(self.event)
        started = threading.Event()
        release = threading.Event()
        results = []
        errors = []
        workers = []
        latest = []

        def newer_assessor(request):
            started.set()
            if not release.wait(5):
                raise AssertionError("new assessment was not released")
            return {"decision": "keep"}

        def newer():
            try:
                results.append(self.assess(decision=newer_assessor))
            except Exception as error:
                errors.append(error)

        def older_assessor(request):
            api.submit_prompt(self.event)
            worker = threading.Thread(target=newer)
            workers.append(worker)
            worker.start()
            self.assertTrue(started.wait(5))
            latest.append(read_state(path))
            return {"decision": "keep"}

        try:
            output = self.assess(decision=older_assessor)
            self.assertIn(
                "superseded",
                output["hookSpecificOutput"]["additionalContext"].casefold(),
            )
            self.assertEqual(read_state(path), latest[0])
        finally:
            release.set()
            for worker in workers:
                worker.join(5)
                self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(read_state(path)["phase"], "passed")
        self.assertEqual(self.received, [])

    def stage_and_queue(self):
        api.submit_prompt(self.event)
        self.assess(
            decision=lambda request: {
                "decision": "recommend_stronger",
                "active_model": "gpt-6-luna",
                "active_effort": "low",
                "active_speed": None,
                "recommended_model": "gpt-6.1-sol",
                "recommended_effort": "high",
                "recommended_speed": None,
                "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
                "official_guidance": "fixture",
                "task_inference": "fixture",
            }
        )
        self.profile = {"model": "gpt-6.1-sol", "effort": "high", "speed": None}
        api.enqueue_handoff(
            "submitted-thread", "source-turn", native_factory=lambda cwd: self.reader
        )
        self.assertEqual(self.received, [self.content])
        self.message_client = "source-turn"
        self.consumed_content = self.received[0]

    def test_old_ready_result_cannot_complete_a_new_identical_submission(self):
        api.submit_prompt(self.event)
        latest = []
        render = HookPresentation.control_context

        def receive_new_submission(thread, turn, state):
            api.submit_prompt(self.event)
            latest.append(read_state(state_path("submitted-thread")))
            return render(thread, turn, state)

        with patch.object(
            HookPresentation, "control_context", side_effect=receive_new_submission
        ):
            output = self.assess(
                decision=lambda _: {
                    "decision": "recommend_stronger",
                    "active_model": "gpt-6-luna",
                    "active_effort": "low",
                    "active_speed": None,
                    "recommended_model": "gpt-6.1-sol",
                    "recommended_effort": "high",
                    "recommended_speed": None,
                    "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
                    "official_guidance": "fixture",
                    "task_inference": "fixture",
                }
            )
        self.assertIn(
            "superseded", output["hookSpecificOutput"]["additionalContext"].casefold()
        )
        self.assertEqual(read_state(state_path("submitted-thread")), latest[0])
        self.assertEqual(self.received, [])
        self.assess()
        self.assertEqual(read_state(state_path("submitted-thread"))["phase"], "passed")

    def test_native_queue_identity_binds_once_without_reassessing_unchanged_input(self):
        self.stage_and_queue()
        api.submit_prompt(
            {**self.event, "turn_id": "native-replay", "model": "gpt-6.1-sol"}
        )
        output = self.assess(
            decision=lambda _: self.fail("Unchanged native replay reassessed")
        )
        self.assertIn(
            "model fit handoff is complete",
            output["hookSpecificOutput"]["additionalContext"].casefold(),
        )
        self.assertEqual(
            read_state(state_path("submitted-thread"))["replay_turn_id"],
            "native-replay",
        )
        self.assertEqual(len(self.received), 1)

    def test_unprepared_technical_commands_are_denied_without_blocking_ordinary_work(
        self,
    ):
        path = state_path("submitted-thread")
        path.parent.mkdir(parents=True, exist_ok=True)
        commands = [
            {
                "tool_name": "mcp__codex_app__send_message_to_thread",
                "tool_input": {
                    "threadId": "foreign-thread",
                    "model": "gpt-6.1-sol",
                    "thinking": "high",
                    "prompt": CONTROL_PROMPT,
                },
            },
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": queue_command("foreign-thread", "foreign-source")
                },
            },
        ]
        for state in (
            None,
            {"phase": "passed", "source_turn_id": "source-turn"},
            {"phase": "ready", "source_turn_id": "older-turn"},
        ):
            with self.subTest(state=state):
                if state is None:
                    path.unlink(missing_ok=True)
                else:
                    write_state(path, state)
                before = path.read_bytes() if path.exists() else None
                for command in commands:
                    result = api.guard_tool({**self.event, **command})
                    self.assertEqual(
                        result["hookSpecificOutput"]["permissionDecision"], "deny"
                    )
                self.assertIsNone(
                    api.guard_tool(
                        {
                            **self.event,
                            "tool_name": "Bash",
                            "tool_input": {"command": "pwd"},
                        }
                    )
                )
                self.assertEqual(path.read_bytes() if path.exists() else None, before)
        write_state(path, {"phase": "passed", "source_turn_id": "source-turn"})
        with locked_state(
            "submitted-thread", operation="fixture", turn_id="source-turn"
        ):
            for command in commands:
                result = api.guard_tool({**self.event, **command})
                self.assertEqual(
                    result["hookSpecificOutput"]["permissionDecision"], "deny"
                )
            self.assertIsNone(
                api.guard_tool(
                    {
                        **self.event,
                        "tool_name": "Bash",
                        "tool_input": {"command": "pwd"},
                    }
                )
            )
        self.assertEqual(self.received, [])

    def test_steering_before_assessment_keeps_source_validation_and_queues_complete_input(
        self,
    ):
        self.steering = [
            {"type": "text", "text": "Include the annotated edges", "text_elements": []}
        ]
        complete = self.content + self.steering
        api.submit_prompt(self.event)
        observed = []

        def recommend(request):
            observed.append(request)
            return {
                "decision": "recommend_stronger",
                "active_model": "gpt-6-luna",
                "active_effort": "low",
                "active_speed": None,
                "recommended_model": "gpt-6.1-sol",
                "recommended_effort": "high",
                "recommended_speed": None,
                "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
                "official_guidance": "fixture",
                "task_inference": "fixture",
            }

        self.assess(decision=recommend)
        self.assertEqual(observed[0]["input"], complete)
        self.assertIn("Include the annotated edges", observed[0]["task"])
        self.profile = {"model": "gpt-6.1-sol", "effort": "high", "speed": None}
        result = api.enqueue_handoff(
            "submitted-thread", "source-turn", native_factory=lambda cwd: self.reader
        )
        self.assertEqual(result["status"], "queued")
        self.assertEqual(self.received, [complete])
        self.consumed_content = self.received[0]
        self.message_client = "source-turn"
        api.submit_prompt(
            {**self.event, "turn_id": "steered-replay", "model": "gpt-6.1-sol"}
        )
        self.assess(decision=lambda _: self.fail("Steered replay was reassessed"))
        self.assertEqual(
            read_state(state_path("submitted-thread"))["replay_turn_id"],
            "steered-replay",
        )
        self.assertEqual(len(self.received), 1)

    def test_repeated_bound_replay_assessment_preserves_confirmed_context(self):
        self.stage_and_queue()
        self.message_client = "source-turn"
        api.submit_prompt(
            {**self.event, "turn_id": "confirmed-replay", "model": "gpt-6.1-sol"}
        )
        first = self.assess(decision=lambda _: self.fail("Replay was reassessed"))
        before = state_path("submitted-thread").read_bytes()
        repeated = self.assess(
            decision=lambda _: self.fail("Repeated replay called the evaluator")
        )
        self.assertEqual(repeated, first)
        self.assertEqual(state_path("submitted-thread").read_bytes(), before)
        self.assertEqual(len(self.received), 1)

    def test_repeated_queued_assessment_does_not_claim_execution_before_consumption(
        self,
    ):
        self.stage_and_queue()
        before = state_path("submitted-thread").read_bytes()
        output = self.assess(
            decision=lambda _: self.fail("Queued request was reassessed")
        )
        self.assertEqual(output, HookPresentation.queued_context())
        self.assertEqual(state_path("submitted-thread").read_bytes(), before)
        self.assertEqual(len(self.received), 1)

    def test_keep_stop_does_not_judge_multimodal_input_as_plain_text(self):
        api.submit_prompt(self.event)
        self.assess()
        with patch(
            "model_fit.infrastructure.adapters.codex.answer.classify_answer"
        ) as judge:
            result = api.guard_replay_answer(
                {
                    **self.event,
                    "last_assistant_message": "A visual answer",
                    "stop_hook_active": False,
                },
                native_factory=lambda _: self.reader,
            )
        self.assertIsNone(result)
        judge.assert_not_called()

    def test_keep_stop_rejects_answer_to_an_old_request(self):
        self.content = [
            {
                "type": "text",
                "text": "Change humidity thresholds and sensor; leave buttons unchanged.",
            }
        ]
        self.event["prompt"] = self.content[0]["text"]
        api.submit_prompt(self.event)
        self.assess()
        answer = "The virtual machine stopped responding four days ago; here are its old kernel logs."
        with patch(
            "model_fit.infrastructure.adapters.codex.answer.classify_answer",
            return_value="unrelated",
        ) as judge:
            result = api.guard_replay_answer(
                {
                    **self.event,
                    "last_assistant_message": answer,
                    "stop_hook_active": False,
                },
                native_factory=lambda _: self.reader,
            )
        self.assertEqual(result["decision"], "block")
        judge.assert_called_once_with(self.event["prompt"], "", answer)
        self.assertEqual(
            read_state(state_path("submitted-thread"))["assessment_decision"], "keep"
        )
        self.assertIsNone(
            api.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )

    def test_keep_stop_allows_relevant_or_uncertain_answer_and_does_not_repeat_correction(
        self,
    ):
        self.content = [{"type": "text", "text": "Prepare the local form."}]
        api.submit_prompt(self.event)
        self.assess()
        event = {
            **self.event,
            "last_assistant_message": "The form is implemented; build passed.",
            "stop_hook_active": False,
        }
        for verdict in ("relevant", "uncertain"):
            with (
                self.subTest(verdict=verdict),
                patch(
                    "model_fit.infrastructure.adapters.codex.answer.classify_answer",
                    return_value=verdict,
                ),
            ):
                self.assertIsNone(
                    api.guard_replay_answer(event, native_factory=lambda _: self.reader)
                )
        with patch(
            "model_fit.infrastructure.adapters.codex.answer.classify_answer"
        ) as judge:
            self.assertIsNone(
                api.guard_replay_answer(
                    {**event, "stop_hook_active": True},
                    native_factory=lambda _: self.reader,
                )
            )
            judge.assert_not_called()

    def test_keep_stop_discards_verdict_after_new_submission(self):
        self.content = [{"type": "text", "text": "Prepare the local form."}]
        api.submit_prompt(self.event)
        self.assess()

        def changed(*_):
            api.submit_prompt(
                {**self.event, "turn_id": "new-source", "prompt": "A different request"}
            )
            return "unrelated"

        with patch(
            "model_fit.infrastructure.adapters.codex.answer.classify_answer",
            side_effect=changed,
        ):
            self.assertIsNone(
                api.guard_replay_answer(
                    {
                        **self.event,
                        "last_assistant_message": "An old answer",
                        "stop_hook_active": False,
                    },
                    native_factory=lambda _: self.reader,
                )
            )
        self.assertEqual(
            read_state(state_path("submitted-thread"))["pending_assessment"]["turn_id"],
            "new-source",
        )

    def test_keep_stop_discards_verdict_after_native_steering_without_state_change(
        self,
    ):
        self.content = [{"type": "text", "text": "Prepare the local form."}]
        api.submit_prompt(self.event)
        self.assess()
        before = state_path("submitted-thread").read_bytes()

        def steered(*_):
            self.steering = [
                {"type": "text", "text": "Instead, explain the old VM incident."}
            ]
            return "unrelated"

        with patch(
            "model_fit.infrastructure.adapters.codex.answer.classify_answer",
            side_effect=steered,
        ):
            result = api.guard_replay_answer(
                {
                    **self.event,
                    "last_assistant_message": "The old VM incident",
                    "stop_hook_active": False,
                },
                native_factory=lambda _: self.reader,
            )
        self.assertIsNone(result)
        self.assertEqual(state_path("submitted-thread").read_bytes(), before)

    def test_unknown_or_foreign_keep_stop_does_not_claim_answer_was_checked(self):
        self.content = [{"type": "text", "text": "Prepare the local form."}]
        api.submit_prompt(self.event)
        self.assess(decision=lambda _: {"decision": "unknown"})
        with patch(
            "model_fit.infrastructure.adapters.codex.answer.classify_answer"
        ) as judge:
            self.assertIsNone(
                api.guard_replay_answer(
                    {
                        **self.event,
                        "last_assistant_message": "Answer",
                        "stop_hook_active": False,
                    },
                    native_factory=lambda _: self.reader,
                )
            )
            judge.assert_not_called()
        write_state(
            state_path("submitted-thread"),
            {
                "phase": "passed",
                "source_turn_id": "foreign-turn",
                "assessment_decision": "keep",
            },
        )
        with patch(
            "model_fit.infrastructure.adapters.codex.answer.classify_answer"
        ) as judge:
            self.assertIsNone(
                api.guard_replay_answer(
                    {
                        **self.event,
                        "last_assistant_message": "Answer",
                        "stop_hook_active": False,
                    },
                    native_factory=lambda _: self.reader,
                )
            )
            judge.assert_not_called()

    def test_low_level_preparation_cannot_guess_native_replay_from_matching_text(self):
        self.stage_and_queue()
        path = state_path("submitted-thread")
        saved = path.read_bytes()
        output = api.prepare_handoff(
            {**self.event, "turn_id": "another-source"},
            context_reader=lambda _: self.fail(
                "Native replay identity was guessed from text"
            ),
        )
        self.assertEqual(output["decision"], "block")
        self.assertEqual(path.read_bytes(), saved)

    def test_previously_queued_marked_input_binds_without_producing_a_new_marker(self):
        retained = copy.deepcopy(self.content)
        retained[0]["text"] += "\n\n<!-- model-fit-replay:retained -->"
        self.profile = {"model": "gpt-6.1-sol", "effort": "high", "speed": None}
        self.message_client = "retained-source"
        self.consumed_content = retained
        path = state_path("submitted-thread")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_state(
            path,
            {
                "phase": "queued",
                "source_turn_id": "retained-source",
                "queued_submission_id": "retained-receipt",
                "queued_input_digest": input_digest(retained),
                "target_model": "gpt-6.1-sol",
                "target_effort": "high",
            },
        )
        api.submit_prompt(
            {
                **self.event,
                "turn_id": "retained-replay",
                "model": "gpt-6.1-sol",
                "prompt": retained[0]["text"],
            }
        )
        self.assess(
            decision=lambda _: self.fail("Retained native replay was reassessed")
        )
        self.assertEqual(read_state(path)["replay_turn_id"], "retained-replay")
        self.assertEqual(self.received, [])

    def test_edited_queue_body_is_the_assessed_body_and_is_not_overwritten(self):
        self.stage_and_queue()
        edited = [
            {
                "type": "text",
                "text": "Edited annotation",
                "text_elements": [
                    {"byteRange": {"start": 0, "end": 6}, "placeholder": "changed"}
                ],
            },
            self.content[2],
            self.content[1],
        ]
        self.consumed_content = edited
        api.submit_prompt(
            {
                **self.event,
                "turn_id": "edited-replay",
                "prompt": "Edited annotation",
                "model": "gpt-6.1-sol",
            }
        )
        observed = []
        self.assess(
            decision=lambda request: (
                observed.append(request["input"]) or {"decision": "keep"}
            )
        )
        self.assertEqual(observed, [edited])
        self.assertEqual(self.consumed_content, edited)
        self.assertEqual(len(self.received), 1)
        self.assertEqual(
            read_state(state_path("submitted-thread"))["source_turn_id"],
            "edited-replay",
        )

    def test_another_submission_cannot_discard_a_still_pending_native_queue_receipt(
        self,
    ):
        self.stage_and_queue()
        self.pending_queue = ["native-receipt"]
        self.message_client = "another-composer-message"
        api.submit_prompt(
            {**self.event, "turn_id": "new-source", "model": "gpt-6.1-sol"}
        )
        with self.assertRaisesRegex(RuntimeError, "still queued"):
            self.assess(
                decision=lambda _: self.fail("A pending queue receipt was discarded")
            )
        state = read_state(state_path("submitted-thread"))
        self.assertEqual(
            (state["phase"], state["source_turn_id"], state["queued_submission_id"]),
            ("queued", "source-turn", "native-receipt"),
        )
        self.assertEqual(len(self.received), 1)
        self.pending_queue = []
        self.message_client = "source-turn"
        api.submit_prompt(
            {**self.event, "turn_id": "original-replay", "model": "gpt-6.1-sol"}
        )
        self.assess(decision=lambda _: self.fail("Unchanged replay was reassessed"))
        self.assertEqual(
            read_state(state_path("submitted-thread"))["replay_turn_id"],
            "original-replay",
        )
        self.assertEqual(len(self.received), 1)

    def test_native_profile_override_is_preserved_also_when_queued_input_was_edited(
        self,
    ):
        self.stage_and_queue()
        self.profile = {"model": "gpt-6.1-terra", "effort": "max", "speed": None}
        self.consumed_content = [
            dict(self.content[0], text="Changed work"),
            self.content[2],
        ]
        api.submit_prompt(
            {**self.event, "turn_id": "edited-replay", "model": "gpt-6.1-terra"}
        )
        output = self.assess(
            decision=lambda _: self.fail("Native profile override was reassessed")
        )
        self.assertIn(
            "suitability was not reassessed here",
            output["hookSpecificOutput"]["additionalContext"].casefold(),
        )
        state = read_state(state_path("submitted-thread"))
        self.assertEqual(state["native_profile"], self.profile)
        self.assertEqual(state["phase"], "passed")
        self.assertNotIn("pending_assessment", state)
        self.assertEqual(len(self.received), 1)
        api.submit_prompt(
            {**self.event, "turn_id": "followup", "model": "gpt-6.1-terra"}
        )
        observed = []
        self.assess(
            decision=lambda request: observed.append(request) or {"decision": "keep"}
        )
        self.assertIn("Retain the selected profile", observed[0]["context"])
        self.assertEqual(
            read_state(state_path("submitted-thread"))["native_profile"], self.profile
        )

    def test_native_profile_choice_survives_a_new_composer_message(self):
        profiles = [
            {"model": "gpt-6.1-terra", "effort": "medium", "speed": None},
            {"model": "gpt-6.1-sol", "effort": "low", "speed": None},
        ]
        for profile in profiles:
            with (
                self.subTest(profile=profile),
                tempfile.TemporaryDirectory() as home,
                patch.dict(os.environ, {"CODEX_HOME": home}),
            ):
                self.received.clear()
                self.profile = {"model": "gpt-6-luna", "effort": "low", "speed": None}
                self.stage_and_queue()
                api.submit_prompt(
                    {
                        **self.event,
                        "turn_id": "completed-replay",
                        "model": "gpt-6.1-sol",
                    }
                )
                self.assess(
                    decision=lambda _: self.fail("Unchanged replay was reassessed")
                )
                self.profile = profile
                self.message_client = "new-composer-client"
                self.consumed_content = [
                    dict(self.content[0], text="Continue current work"),
                    *self.content[1:],
                ]
                event = {
                    **self.event,
                    "turn_id": "new-source",
                    "prompt": "Continue current work",
                    "model": profile["model"],
                }
                api.submit_prompt(event)
                observed = []
                self.assess(
                    decision=lambda request: (
                        observed.append(request) or {"decision": "keep"}
                    )
                )
                self.assertEqual(len(observed), 1)
                self.assertEqual(observed[0]["active_profile"], profile)
                self.assertEqual(observed[0]["input"], self.consumed_content)
                self.assertIn(
                    "checking the accepted current message",
                    observed[0]["context"].casefold(),
                )
                self.assertIn(str(profile), observed[0]["context"])
                state = read_state(state_path("submitted-thread"))
                self.assertEqual(state["native_profile"], profile)
                self.assertEqual(state["profile_context_turn_id"], "new-source")
                self.assertEqual(state["phase"], "passed")
                self.assertNotIn("pending_assessment", state)
                self.assertEqual(len(self.received), 1)
                self.assertIsNone(
                    api.guard_tool(
                        {**event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
                    )
                )

    def test_unchanged_native_profile_on_new_composer_input_is_still_assessed(self):
        self.stage_and_queue()
        self.message_client = "new-composer-client"
        api.submit_prompt(
            {**self.event, "turn_id": "new-source", "model": "gpt-6.1-sol"}
        )
        assessed = []
        self.assess(
            decision=lambda request: assessed.append(request) or {"decision": "keep"}
        )
        self.assertEqual(len(assessed), 1)
        self.assertNotIn("native_profile", read_state(state_path("submitted-thread")))
        self.assertEqual(len(self.received), 1)

    def test_native_profile_choice_cannot_discard_an_outstanding_queue_receipt(self):
        self.stage_and_queue()
        self.pending_queue = ["native-receipt"]
        self.profile = {"model": "gpt-6.1-terra", "effort": "medium", "speed": None}
        self.message_client = "new-composer-client"
        api.submit_prompt(
            {**self.event, "turn_id": "new-source", "model": "gpt-6.1-terra"}
        )
        with self.assertRaisesRegex(RuntimeError, "still queued"):
            self.assess(decision=lambda _: self.fail("Outstanding queue was discarded"))
        state = read_state(state_path("submitted-thread"))
        self.assertEqual(
            (state["phase"], state["source_turn_id"], state["queued_submission_id"]),
            ("queued", "source-turn", "native-receipt"),
        )
        self.assertEqual(len(self.received), 1)

    def test_current_request_can_reselect_a_changed_native_profile(self):
        self.stage_and_queue()
        self.profile = {"model": "gpt-6.1-terra", "effort": "medium", "speed": None}
        self.message_client = "new-composer-client"
        self.consumed_content = [
            dict(self.content[0], text="Reassess this profile"),
            *self.content[1:],
        ]
        api.submit_prompt(
            {
                **self.event,
                "turn_id": "new-source",
                "model": "gpt-6.1-terra",
                "prompt": "Reassess this profile",
            }
        )
        observed = []

        def reselect(request):
            observed.append(request)
            return {
                "decision": "recommend_lighter",
                "active_model": "gpt-6.1-terra",
                "active_effort": "medium",
                "active_speed": None,
                "recommended_model": "gpt-6-luna",
                "recommended_effort": "low",
                "recommended_speed": None,
                "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
                "official_guidance": "fixture",
                "task_inference": "fixture",
            }

        self.assess(decision=reselect)
        self.assertEqual(observed[0]["task"], "Reassess this profile")
        self.assertIn(
            "checking the accepted current message", observed[0]["context"].casefold()
        )
        state = read_state(state_path("submitted-thread"))
        self.assertEqual(
            (state["phase"], state["target_model"], state["target_effort"]),
            ("ready", "gpt-6-luna", "low"),
        )
        self.assertNotIn("native_profile", state)
        self.assertEqual(len(self.received), 1)

    def test_unsupported_speed_cannot_admit_work_while_preserving_profile_choice_context(
        self,
    ):
        path = state_path("submitted-thread")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_state(
            path,
            {
                "phase": "passed",
                "source_turn_id": "earlier",
                "profile_context_turn_id": "choice",
            },
        )
        api.submit_prompt(self.event)
        output = self.assess(
            decision=lambda request: {
                "decision": "recommend_stronger",
                "active_model": "gpt-6-luna",
                "active_effort": "low",
                "active_speed": None,
                "recommended_model": "gpt-6.1-sol",
                "recommended_effort": "high",
                "recommended_speed": "fast",
                "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
                "official_guidance": "fixture",
                "task_inference": "fixture",
            }
        )
        self.assertEqual(output["decision"], "block")
        state = read_state(path)
        self.assertEqual(state["pending_assessment"]["status"], "failed")
        self.assertEqual(state["profile_context_turn_id"], "choice")
        denied = api.guard_tool(
            {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_verified_effort_change_clears_stale_manual_block_for_attachment_only_input(
        self,
    ):
        cache = FileRecommendations()
        cache.save(
            "submitted-thread",
            {"task": "", "active_profile": self.profile},
            {
                "decision": "recommend_stronger",
                "active_model": "gpt-6-luna",
                "active_effort": "low",
                "active_speed": None,
                "recommended_model": "gpt-6.1-sol",
                "recommended_effort": "high",
                "recommended_speed": None,
                "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
                "official_guidance": "fixture",
                "task_inference": "fixture",
            },
        )
        self.content = self.content[1:]
        self.consumed_content = self.content
        api.submit_prompt({**self.event, "prompt": ""})
        self.assertNotEqual(
            self.assess(decision=lambda _: {"decision": "unknown"}).get("decision"),
            "block",
        )
        self.assertIsNone(cache.load("submitted-thread"))
        self.profile = {"model": "gpt-6-luna", "effort": "medium", "speed": None}
        api.submit_prompt({**self.event, "turn_id": "new-profile-turn", "prompt": ""})
        observed = []
        output = self.assess(
            decision=lambda request: observed.append(request) or {"decision": "keep"}
        )
        self.assertNotEqual(output.get("decision"), "block")
        self.assertEqual(observed[0]["input"], self.content)
        self.assertEqual(observed[0]["active_profile"], self.profile)
        self.assertIsNone(cache.load("submitted-thread"))
        self.assertEqual(
            read_state(state_path("submitted-thread"))["assessment_decision"], "keep"
        )
        self.assertIsNone(
            api.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )

    def test_new_submission_fences_an_assessment_already_running_with_same_text(self):
        api.submit_prompt(self.event)
        first_generation = read_state(state_path("submitted-thread"))[
            "pending_assessment"
        ]["generation"]

        def receive_steering(request):
            api.submit_prompt(self.event)
            return {"decision": "keep"}

        output = self.assess(decision=receive_steering)
        self.assertIn(
            "superseded", output["hookSpecificOutput"]["additionalContext"].casefold()
        )
        pending = read_state(state_path("submitted-thread"))["pending_assessment"]
        self.assertNotEqual(pending["generation"], first_generation)
        self.assertEqual(pending["status"], "waiting")
        self.assertIsNotNone(
            api.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )
        self.assess()
        self.assertIsNone(
            api.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )

    def test_steering_in_an_assessed_turn_is_reassessed_with_accepted_attachments(self):
        api.submit_prompt(self.event)
        self.assess()
        self.content = [
            *self.content,
            {"type": "text", "text": "New annotation", "text_elements": []},
            {"type": "audio", "opaque": "native-fixture"},
        ]
        api.submit_prompt({**self.event, "prompt": "New annotation"})
        observed = []
        self.assess(
            decision=lambda request: (
                observed.append(request["input"]) or {"decision": "keep"}
            )
        )
        self.assertEqual(observed, [self.content])

    def test_lock_contention_does_not_admit_unassessed_steering_after_a_pass(self):
        api.submit_prompt(self.event)
        self.assess()
        api.submit_prompt(self.event)
        with locked_state("submitted-thread"):
            output = api.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assess()
        self.assertIsNone(
            api.guard_tool(
                {**self.event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            )
        )

    def test_capability_and_transport_failure_do_not_block_ordinary_work(self):
        for code, message, unavailable in [
            (-32600, "thread not loaded: submitted-thread", True),
            (-32000, "authentication unavailable", False),
        ]:
            with self.subTest(code=code):
                api.submit_prompt(self.event)
                error = AppServerRPCError(
                    message,
                    method="thread/read",
                    code=code,
                    thread_id="submitted-thread",
                )

                def fail_context(event, error=error):
                    raise error

                if unavailable:
                    output = api.assess_submitted(context_reader=fail_context)
                    self.assertIn(
                        "suitability is unknown", output["systemMessage"].casefold()
                    )
                    self.assertEqual(
                        read_state(state_path("submitted-thread"))[
                            "assessment_decision"
                        ],
                        "unknown",
                    )
                else:
                    output = api.assess_submitted(context_reader=fail_context)
                    self.assertIn(
                        "continue the original task", output["systemMessage"].casefold()
                    )
                    self.assertEqual(
                        read_state(state_path("submitted-thread"))[
                            "assessment_decision"
                        ],
                        "unknown",
                    )
                    self.assertIsNone(
                        api.guard_tool(
                            {
                                **self.event,
                                "tool_name": "Bash",
                                "tool_input": {"command": "pwd"},
                            }
                        )
                    )
                state_path("submitted-thread").unlink()
