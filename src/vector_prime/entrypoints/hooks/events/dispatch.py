from __future__ import annotations
import json
import os
import subprocess
import sys
from vector_prime.application.submission.types.json import JsonValue
from vector_prime.application.submission.decoding import (
    checked_object,
    native_optional_text,
    native_text,
)
from vector_prime.entrypoints.hooks.activation import (
    automatic_allowed,
    inactive_output,
    record_unavailable,
)
from vector_prime.entrypoints.hooks.native_contract import AUTO_THREAD_ENV
from vector_prime.entrypoints.hooks.operations import (
    guard_replay_answer,
    guard_tool,
    submit_prompt,
)
from vector_prime.entrypoints.hooks.response import deny_tool
from vector_prime.entrypoints.hooks.events.identity import executor_thread_id
from vector_prime.infrastructure.adapters.filesystem.audit import (
    failure_location,
    record_audit,
)


def handle_event(
    *,
    check_admission: bool = False,
    event: dict[str, JsonValue] | None = None,
    expected_thread: str | None = None,
) -> int:
    auto_thread = expected_thread or os.environ.get(AUTO_THREAD_ENV)
    turn_id = None
    event_name = None
    try:
        if event is None:
            event = checked_object(json.load(sys.stdin))
        if not isinstance(event, dict):
            raise ValueError("Invalid Desktop hook event")
        if not auto_thread or executor_thread_id(event) != auto_thread:
            return 0
        event_name = native_optional_text(event.get("hook_event_name"))
        turn_id = native_optional_text(event.get("turn_id"))
        admitted = (
            automatic_allowed(
                event_name or "",
                native_text(event.get("cwd") or os.getcwd()),
                direct=True,
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
            output = submit_prompt(event)
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
                    "Stop", native_text(event.get("cwd") or os.getcwd()), direct=True
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
                {
                    **(
                        {"hook_event": event_name}
                        if isinstance(event_name, str)
                        else {}
                    ),
                    **failure_location(error),
                },
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
