"""Opt-in Desktop Model Fit handoff to a queued turn on the selected profile."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from model_fit.handoff import (
    CONTROL_PROMPT,
    REPLAY_CONTEXT,
    queue_command,
    prepare as prepare_handoff,
)
from model_fit.app_server import AppServerRPCError, AppServerReader
from model_fit.queue import (
    QUEUE_PAGE_LIMIT,
    RPC_TIMEOUT_SECONDS,
)
from model_fit.state import (
    locked_state,
    lock_owner,
    read_state,
    state_path,
    write_state,
)
from model_fit.input import (
    prompt_digest,
    input_text,
    input_digest,
    source_input,
    replay_input,
    queue_input_matches,
)
from model_fit.audit import record_audit
from model_fit.recommendation import session_input, triage


AUTO_THREAD_ENV = "MODEL_FIT_AUTO_THREAD"
HANDOFF_TTL_SECONDS = 300
MAX_REPLAY_EVAL_CHARS = 8000
REPLAY_STOP_REASON = (
    "Последний ответ относился к другой задаче. Сверь его с исходным запросом "
    "этого replay-хода и продолжи незавершённую работу. Уже выполненные действия "
    "не повторяй; перед новым действием проверь их результат."
)


def failure_location(error: BaseException) -> dict[str, Any]:
    frames = traceback.extract_tb(error.__traceback__)
    if not frames:
        return {}
    frame = frames[-1]
    return {
        "failure_file": Path(frame.filename).name,
        "failure_function": frame.name,
        "failure_line": frame.lineno,
    }


def guard_tool(event: dict[str, Any]) -> dict[str, Any] | None:
    thread_id = event["session_id"]
    try:
        with locked_state(
            thread_id,
            nonblocking=True,
            operation="pre_tool_use",
            turn_id=event.get("turn_id"),
        ) as path:
            state = read_state(path)
    except BlockingIOError:
        state = read_state(state_path(thread_id))
        details = {
            "hook_event": "PreToolUse",
            "state_phase": state["phase"] if state else "missing",
        }
        details.update(lock_owner(thread_id))
        if (
            state is not None
            and state["phase"] == "passed"
            and state["source_turn_id"] == event.get("turn_id")
        ):
            record_audit(
                thread_id,
                event.get("turn_id"),
                "auto_guard_lock_contention",
                details | {"reason_code": "passed_same_turn"},
            )
            return None
        record_audit(
            thread_id,
            event.get("turn_id"),
            "auto_guard_block",
            details | {"reason_code": "state_lock_busy"},
        )
        return deny_tool(
            "Model Fit: состояние переноса занято; технический ход не допускает новый инструмент."
        )
    if (
        state is None
        or state["phase"] == "passed"
        or state["source_turn_id"] != event.get("turn_id")
    ):
        return None
    tool = event.get("tool_name")
    arguments = event.get("tool_input")
    if state["phase"] == "ready" and isinstance(arguments, dict):
        if tool == "mcp__codex_app__send_message_to_thread" and all(
            (
                arguments.get("threadId") == thread_id,
                arguments.get("model") == state["target_model"],
                arguments.get("thinking") == state["target_effort"],
                arguments.get("prompt") == CONTROL_PROMPT,
            )
        ):
            return None
        if tool == "Bash" and arguments.get("command") == queue_command(
            thread_id, state["source_turn_id"]
        ):
            return None
    record_audit(
        thread_id,
        event.get("turn_id"),
        "auto_guard_block",
        {
            "hook_event": "PreToolUse",
            "reason_code": "technical_turn_tool_denied",
            "state_phase": state["phase"],
        },
    )
    return deny_tool(
        "Model Fit: технический ход допускает только смену профиля и постановку исходного запроса в очередь."
    )


def deny_tool(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def prepare(event: dict[str, Any]) -> dict[str, Any] | None:
    return prepare_handoff(event, AppServerReader, session_input, triage)


def enqueue(thread_id: str, turn_id: str) -> dict[str, str]:
    caller_thread = os.environ.get("CODEX_THREAD_ID")
    if caller_thread and caller_thread != thread_id:
        raise ValueError("Queue helper must run in the target Desktop thread")
    with locked_state(thread_id, operation="queue", turn_id=turn_id) as path:
        state = read_state(path)
        if state is None or state["source_turn_id"] != turn_id:
            raise ValueError("No matching Model Fit handoff")
        if state["phase"] == "queued":
            return {
                "queued_submission_id": state["queued_submission_id"],
                "status": "already_queued",
            }
        if state["phase"] == "rejected":
            raise RuntimeError("Queue rejected this handoff; send a new prompt")
        if state["phase"] != "ready":
            raise RuntimeError(
                "Previous queue attempt has an unknown outcome; do not retry"
            )
        if time.time() - state["created_at"] > HANDOFF_TTL_SECONDS:
            raise ValueError("Model Fit handoff expired")
        prompt = state["prompt"]
        with AppServerReader(os.getcwd()) as app:
            thread = app.call(
                "thread/read",
                {"threadId": thread_id, "includeTurns": False},
                RPC_TIMEOUT_SECONDS,
            )["thread"]
            if (thread.get("model"), thread.get("reasoningEffort")) != (
                state["target_model"],
                state["target_effort"],
            ):
                raise ValueError("Target profile was not applied to the next turn")
            content = source_input(app, thread_id, turn_id)
            if input_text(content) != prompt:
                raise ValueError(
                    "Source user input does not match the submitted prompt"
                )
            queued_input = replay_input(content, secrets.token_hex(16))
            state.pop("prompt")
            state["source_input_digest"] = input_digest(content)
            state["queued_input_digest"] = input_digest(queued_input)
            state["queued_prompt_digest"] = prompt_digest(input_text(queued_input))
            state["phase"] = "attempting"
            write_state(path, state)
            try:
                result = app.call(
                    "thread/queue/add",
                    {
                        "threadId": thread_id,
                        "clientUserMessageId": turn_id,
                        "input": queued_input,
                    },
                    RPC_TIMEOUT_SECONDS,
                )
            except AppServerRPCError:
                state["phase"] = "rejected"
                write_state(path, state)
                raise
            submission = result["queuedSubmission"]
            state["queued_submission_id"] = submission["id"]
            if not queue_input_matches(queued_input, submission["input"]):
                write_state(path, state)
                deleted = app.call(
                    "thread/queue/delete",
                    {
                        "threadId": thread_id,
                        "queuedSubmissionId": submission["id"],
                    },
                    RPC_TIMEOUT_SECONDS,
                ).get("deleted")
                if not deleted:
                    raise RuntimeError(
                        "Native queue input mismatch could not be removed"
                    )
                state["phase"] = "rejected"
                write_state(path, state)
                raise ValueError(
                    "Native queue did not preserve the complete user input"
                )
            state["queued_input_digest"] = input_digest(submission["input"])
        state["phase"] = "queued"
        state["queued_at"] = int(time.time())
        write_state(path, state)
        return {
            "queued_submission_id": state["queued_submission_id"],
            "status": "queued",
        }


def guard_replay_answer(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("stop_hook_active") is True:
        return None
    thread_id = event["session_id"]
    turn_id = event.get("turn_id")
    answer = event.get("last_assistant_message")
    if (
        not isinstance(turn_id, str)
        or not isinstance(answer, str)
        or not answer.strip()
    ):
        return None
    with locked_state(thread_id, operation="stop", turn_id=turn_id) as path:
        state = read_state(path)
    if (
        state is None
        or state["phase"] != "queued"
        or state.get("replay_turn_id") != turn_id
    ):
        return None
    with AppServerReader(event["cwd"]) as app:
        content = source_input(app, thread_id, state["source_turn_id"])
        replay = app.call(
            "thread/items/list",
            {
                "threadId": thread_id,
                "turnId": turn_id,
                "limit": QUEUE_PAGE_LIMIT,
            },
            RPC_TIMEOUT_SECONDS,
        )
    user_messages = [
        entry["item"]
        for entry in replay["data"]
        if entry["item"].get("type") == "userMessage"
    ]
    if replay.get("nextCursor") or len(user_messages) != 1:
        record_audit(thread_id, turn_id, "auto_stop_steered_or_unverified")
        return None
    if (
        input_digest(user_messages[0].get("content", []))
        != state["queued_input_digest"]
    ):
        record_audit(thread_id, turn_id, "auto_stop_input_unverified")
        return None
    if any(item.get("type") != "text" for item in content):
        record_audit(thread_id, turn_id, "auto_stop_multimodal_unchecked")
        return None
    request = input_text(content).strip()
    if (
        not request
        or len(request) > MAX_REPLAY_EVAL_CHARS
        or len(answer) > MAX_REPLAY_EVAL_CHARS
    ):
        record_audit(thread_id, turn_id, "auto_stop_size_unchecked")
        return None
    from answer import classify_answer

    verdict = classify_answer(request, state.get("task_inference", ""), answer)
    record_audit(thread_id, turn_id, f"auto_stop_{verdict}")
    if verdict != "unrelated":
        return None
    with locked_state(thread_id, operation="stop", turn_id=turn_id) as path:
        current = read_state(path)
    if current is None or current.get("replay_turn_id") != turn_id:
        return None
    return {"decision": "block", "reason": REPLAY_STOP_REASON}


def main() -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command")
    queue = subcommands.add_parser("queue")
    queue.add_argument("--thread-id", required=True)
    queue.add_argument("--turn-id", required=True)
    arguments = parser.parse_args()
    if arguments.command == "queue":
        try:
            result = enqueue(arguments.thread_id, arguments.turn_id)
            record_audit(
                arguments.thread_id,
                arguments.turn_id,
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
            record_audit(
                arguments.thread_id,
                arguments.turn_id,
                f"auto_queue_error:{type(error).__name__}",
                {"hook_event": "queue"} | failure_location(error),
            )
            print(f"Model Fit queue failed ({type(error).__name__})", file=sys.stderr)
            return 1
    auto_thread = os.environ.get(AUTO_THREAD_ENV)
    turn_id = None
    event_name = None
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("Invalid Desktop hook event")
        if not auto_thread or event.get("session_id") != auto_thread:
            return 0
        event_name = event.get("hook_event_name")
        turn_id = event.get("turn_id")
        if event_name == "UserPromptSubmit":
            record_audit(
                auto_thread, turn_id, "auto_started", {"hook_event": event_name}
            )
            output = prepare(event)
            outcome = (
                "auto_pass"
                if output is None
                else "auto_replay"
                if output.get("hookSpecificOutput", {}).get("additionalContext")
                == REPLAY_CONTEXT
                else "auto_handoff"
                if "hookSpecificOutput" in output
                else "auto_block"
                if output.get("decision") == "block"
                else "auto_unknown"
            )
            record_audit(auto_thread, turn_id, outcome, {"hook_event": event_name})
        elif event_name == "PreToolUse":
            output = guard_tool(event)
        elif event_name == "Stop":
            output = guard_replay_answer(event)
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
            reason = f"Model Fit: автоматический перенос не подготовлен ({type(error).__name__}); исходная задача не запускалась."
            output = (
                deny_tool(reason)
                if event_name == "PreToolUse"
                else {"decision": "block", "reason": reason}
            )
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
