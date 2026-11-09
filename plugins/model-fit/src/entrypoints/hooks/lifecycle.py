"""CLI and native Desktop hook dispatch for Model Fit."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from model_fit.autoswitch.exceptions.unavailable import SubmissionUnavailable
from model_fit.entrypoints.hooks.activation import (
    automatic_allowed,
    inactive_output,
    record_unavailable,
)
from model_fit.entrypoints.hooks.instructions import (
    admission_unavailable_context,
    inactive_context,
)
from model_fit.entrypoints.hooks.native_contract import AUTO_THREAD_ENV
from model_fit.entrypoints.hooks.operations import (
    assess_submitted,
    guard_replay_answer,
    guard_tool,
    reassess,
)
from model_fit.entrypoints.hooks.operations import enqueue_handoff as enqueue
from model_fit.entrypoints.hooks.operations import submit_prompt as prepare
from model_fit.entrypoints.hooks.response import deny_tool
from model_fit.infrastructure.adapters.codex.identity import executor_thread_id
from model_fit.infrastructure.adapters.filesystem.audit import (
    failure_location,
    record_audit,
)


def queue_handoff(thread_id: str, turn_id: str) -> int:
    audit_thread = (
        os.environ.get("CODEX_THREAD_ID") if thread_id == "current" else thread_id
    )
    audit_turn = None if turn_id == "source" else turn_id
    try:
        result = enqueue(thread_id, turn_id)
        if audit_thread:
            record_audit(
                audit_thread,
                audit_turn,
                f"auto_queue_{result['status']}",
                {"hook_event": "queue"},
            )
        print(json.dumps(result))
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        TimeoutError,
        subprocess.SubprocessError,
    ) as error:
        if audit_thread:
            record_audit(
                audit_thread,
                audit_turn,
                f"auto_queue_error:{type(error).__name__}",
                {"hook_event": "queue", "reason_code": "queue_failed"}
                | failure_location(error),
            )
        print(f"Model Fit queue failed ({type(error).__name__})", file=sys.stderr)
        return 1


def assess_current(
    *, check_admission: bool = False, requirements: str | None = None
) -> int:
    try:
        output = assess_submitted() if requirements is None else reassess(requirements)
    except SubmissionUnavailable as error:
        if error.thread_id:
            record_audit(
                error.thread_id,
                None,
                "auto_assessment_error:SubmissionUnavailable",
                {"hook_event": "assessment", "reason_code": error.reason_code}
                | failure_location(error),
            )
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": "SubmissionUnavailable",
                    "reason_code": error.reason_code,
                }
            )
        )
        return 1
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        TimeoutError,
        subprocess.SubprocessError,
    ) as error:
        thread = os.environ.get("CODEX_THREAD_ID")
        if thread:
            record_audit(
                thread,
                None,
                f"auto_assessment_error:{type(error).__name__}",
                {"hook_event": "assessment", "reason_code": "assessment_failed"}
                | failure_location(error),
            )
        print(json.dumps({"status": "failed", "error": type(error).__name__}))
        return 1
    admitted = (
        automatic_allowed("UserPromptSubmit", os.getcwd()) if check_admission else True
    )
    if admitted is not True:
        thread = os.environ.get("CODEX_THREAD_ID")
        if thread:
            record_audit(
                thread,
                None,
                "auto_assessment_revoked"
                if admitted is False
                else "auto_assessment_admission_unknown",
                {
                    "hook_event": "assessment",
                    "reason_code": "automatic_admission_revoked"
                    if admitted is False
                    else "automatic_admission_unavailable",
                },
            )
        output = (
            inactive_context() if admitted is False else admission_unavailable_context()
        )
    print(json.dumps(output, ensure_ascii=False))
    return 1 if output.get("decision") == "block" else 0


def handle_lifecycle(
    *,
    check_admission: bool = False,
    event: dict[str, Any] | None = None,
    expected_thread: str | None = None,
) -> int:
    auto_thread = expected_thread or os.environ.get(AUTO_THREAD_ENV)
    turn_id = None
    event_name = None
    try:
        if event is None:
            event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("Invalid Desktop hook event")
        if not auto_thread or executor_thread_id(event) != auto_thread:
            return 0
        event_name = event.get("hook_event_name")
        turn_id = event.get("turn_id")
        admitted = (
            automatic_allowed(
                event_name or "", event.get("cwd") or os.getcwd(), direct=True
            )
            if check_admission
            else True
        )
        if admitted is not True:
            if admitted is None:
                record_unavailable(auto_thread, turn_id, event_name or "")
            output = inactive_output(event, admitted)
            if output is not None:
                print(json.dumps(output, ensure_ascii=False))
            return 0
        if event_name == "UserPromptSubmit":
            output = prepare(event)
        elif event_name == "PreToolUse":
            output = guard_tool(event)
        elif event_name == "Stop":
            output = guard_replay_answer(event)
            if (
                check_admission
                and output is not None
                and (output.get("decision") == "block")
            ):
                current_admission = automatic_allowed(
                    "Stop", event.get("cwd") or os.getcwd(), direct=True
                )
                if current_admission is not True:
                    if current_admission is None:
                        record_unavailable(auto_thread, turn_id, "Stop")
                    output = inactive_output(event, current_admission)
        else:
            return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        TimeoutError,
        subprocess.SubprocessError,
    ) as error:
        if auto_thread:
            record_audit(
                auto_thread,
                turn_id,
                f"auto_error:{type(error).__name__}",
                ({"hook_event": event_name} if isinstance(event_name, str) else {})
                | failure_location(error),
            )
        if event_name in (None, "Stop"):
            output = None
        else:
            reason = f"Model Fit: automatic handoff was not prepared ({type(error).__name__}); the original task was not started."
            output = (
                deny_tool(reason)
                if event_name == "PreToolUse"
                else {"decision": "block", "reason": reason}
            )
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0
