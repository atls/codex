"Read native Desktop state, source messages and queue lifecycle."

from __future__ import annotations

import time
from typing import Any, Iterator

from model_fit.entrypoints.hooks.instructions import CONTROL_PROMPT
from model_fit.infrastructure.adapters.codex.codec import (
    hook_prompt,
    input_digest,
    input_text,
    prompt_digest,
)
from model_fit.infrastructure.adapters.codex.identity import executor_thread_id
from model_fit.infrastructure.adapters.codex.transport.connection import (
    AppServerRPCError,
)
from model_fit.infrastructure.adapters.codex.transport.reader import AppServerReader
from model_fit.submission.context import CONTEXT_TURN_LIMIT, recent_context

QUEUE_PAGE_LIMIT = 100
MAX_QUEUE_PAGES = 5
MAX_INPUT_PAGES = 5
RPC_TIMEOUT_SECONDS = 10
INPUT_SCAN_TIMEOUT_SECONDS = 50
TURN_PAGE_LIMIT = 5
CONTEXT_PAGE_LIMIT = 4
TERMINAL_TURN_STATUSES = {"completed", "failed", "interrupted"}


def source_messages(
    app: AppServerReader, thread_id: str, turn_id: str, include_steering: bool = True
) -> list[dict[str, Any]]:
    cursor = None
    seen_cursors: set[str] = set()
    messages = []
    deadline = time.monotonic() + INPUT_SCAN_TIMEOUT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Source input pagination timed out")
        params: dict[str, Any] = {
            "threadId": thread_id,
            "turnId": turn_id,
            "limit": QUEUE_PAGE_LIMIT,
        }
        if cursor is not None:
            params["cursor"] = cursor
        result = app.call(
            "thread/items/list", params, min(RPC_TIMEOUT_SECONDS, remaining)
        )
        for entry in result["data"]:
            item = entry["item"]
            if item.get("type") == "userMessage":
                content = item.get("content")
                if (
                    not isinstance(content, list)
                    or not content
                    or (not all((isinstance(value, dict) for value in content)))
                ):
                    raise ValueError("Source user input is unavailable")
                messages.append(item)
                if not include_steering:
                    return messages
        cursor = result.get("nextCursor")
        if cursor is None:
            if messages:
                return messages
            raise ValueError("Source user input is unavailable")
        if cursor in seen_cursors:
            raise ValueError("Source input pagination repeated a cursor")
        seen_cursors.add(cursor)


def source_input(
    app: AppServerReader,
    thread_id: str,
    turn_id: str,
    include_steering: bool = False,
    expected_prompt: str | None = None,
) -> list[dict[str, Any]]:
    messages = source_messages(app, thread_id, turn_id, include_steering)
    first = messages[0]["content"]
    if expected_prompt is not None and hook_prompt(first) != expected_prompt:
        raise ValueError("Source user input does not match the submitted prompt")
    if not include_steering:
        return first
    return [
        value
        for message in messages
        if input_text(message["content"]).strip() != CONTROL_PROMPT
        for value in message["content"]
    ]


def handoff_input(
    app: AppServerReader, thread_id: str, state: dict[str, Any]
) -> list[dict[str, Any]]:
    content = source_input(
        app,
        thread_id,
        state["source_turn_id"],
        include_steering=True,
        expected_prompt=state.get("prompt"),
    )
    for continuation in state.get("continuation_turn_ids", []):
        content.extend(
            source_input(app, thread_id, continuation, include_steering=True)
        )
    return content


def queued_ids(app: AppServerReader, thread_id: str) -> set[str]:
    ids: set[str] = set()
    cursor = None
    seen_cursors: set[str] = set()
    for _ in range(MAX_QUEUE_PAGES):
        params: dict[str, Any] = {"threadId": thread_id, "limit": QUEUE_PAGE_LIMIT}
        if cursor is not None:
            params["cursor"] = cursor
        result = app.call("thread/queue/list", params, RPC_TIMEOUT_SECONDS)
        ids.update((item["id"] for item in result["data"]))
        cursor = result.get("nextCursor")
        if cursor is None:
            return ids
        if cursor in seen_cursors:
            raise ValueError("Queue pagination repeated a cursor")
        seen_cursors.add(cursor)
    raise ValueError("Queue exceeds the bounded Model Fit scan")


def handoff_turns(app: AppServerReader, thread_id: str) -> Iterator[dict[str, Any]]:
    cursor = None
    seen_cursors: set[str] = set()
    for _ in range(MAX_QUEUE_PAGES):
        params = {
            "threadId": thread_id,
            "limit": TURN_PAGE_LIMIT,
            "itemsView": "summary",
        }
        if cursor is not None:
            params["cursor"] = cursor
        result = app.call("thread/turns/list", params, RPC_TIMEOUT_SECONDS)
        yield from result["data"]
        cursor = result.get("nextCursor")
        if cursor is None:
            return
        if cursor in seen_cursors:
            raise ValueError("Model Fit turn history cursor repeated")
        seen_cursors.add(cursor)
    raise ValueError("Model Fit turn history exceeds bounded pagination")


def replay_finished(
    app: AppServerReader, thread_id: str, state: dict[str, Any]
) -> bool:
    for turn in handoff_turns(app, thread_id):
        replay_turn_id = state.get("replay_turn_id")
        if replay_turn_id is not None:
            if turn.get("id") == replay_turn_id:
                return turn.get("status") in TERMINAL_TURN_STATUSES
            continue
        started_at = turn.get("startedAt")
        if isinstance(started_at, int) and started_at < state.get(
            "created_at", state["queued_at"]
        ):
            return False
        if (
            not isinstance(started_at, int)
            or turn.get("id") == state["source_turn_id"]
            or turn.get("status") not in TERMINAL_TURN_STATUSES
        ):
            continue
        items = app.call(
            "thread/items/list",
            {"threadId": thread_id, "turnId": turn["id"], "limit": 10},
            RPC_TIMEOUT_SECONDS,
        )["data"]
        for entry in items:
            item = entry["item"]
            if item.get("type") == "userMessage":
                content = item.get("content", [])
                matches = (
                    input_digest(content) == state["queued_input_digest"]
                    if "queued_input_digest" in state
                    else prompt_digest(input_text(content))
                    == state["queued_prompt_digest"]
                )
                if matches:
                    return True
                break
    return False


def source_terminal_without_replay(
    app: AppServerReader, thread_id: str, source_turn_id: str, current_turn_id: str
) -> bool:
    for turn in handoff_turns(app, thread_id):
        if turn.get("id") == current_turn_id:
            continue
        if turn.get("status") not in TERMINAL_TURN_STATUSES:
            return False
        if turn.get("id") == source_turn_id:
            return True
    return False


def unsubmitted_successor(
    app: AppServerReader, thread_id: str, source_turn_id: str, current_turn_id: str
) -> bool:
    page = app.call(
        "thread/turns/list",
        {
            "threadId": thread_id,
            "limit": 2,
            "itemsView": "notLoaded",
            "sortDirection": "desc",
        },
        RPC_TIMEOUT_SECONDS,
    )
    turns = page["data"]
    if (
        len(turns) != 2
        or turns[0].get("id") != current_turn_id
        or turns[1].get("id") != source_turn_id
    ):
        return False
    started, completed = (turns[0].get("startedAt"), turns[1].get("completedAt"))
    if (
        type(started) is not int
        or type(completed) is not int
        or completed > started
        or (turns[1].get("status") not in TERMINAL_TURN_STATUSES)
    ):
        return False
    cursor = None
    seen = set()
    for _ in range(MAX_INPUT_PAGES):
        params = {
            "threadId": thread_id,
            "turnId": current_turn_id,
            "limit": QUEUE_PAGE_LIMIT,
        }
        if cursor is not None:
            params["cursor"] = cursor
        items = app.call("thread/items/list", params, RPC_TIMEOUT_SECONDS)
        if any((entry["item"].get("type") == "userMessage" for entry in items["data"])):
            return False
        cursor = items.get("nextCursor")
        if cursor is None:
            return True
        if cursor in seen:
            return False
        seen.add(cursor)
    return False


def unavailable_session_input(error: AppServerRPCError, thread_id: str) -> str | None:
    if error.thread_id != thread_id:
        return None
    if (
        error.method == "thread/read"
        and type(error.code) is int
        and (error.code == -32600)
        and (error.rpc_message == f"thread not loaded: {thread_id}")
    ):
        return "session_thread_not_loaded"
    if (
        error.method == "thread/turns/list"
        and error.rpc_message == "ephemeral threads do not support thread/turns/list"
    ):
        return "session_turns_unsupported"
    return None


def session_input(event: dict[str, Any]) -> dict[str, Any]:
    session_id = executor_thread_id(event)
    prompt = event.get("prompt")
    cwd = event.get("cwd")
    model = event.get("model")
    if not all(
        (isinstance(value, str) and value for value in (session_id, cwd, model))
    ) or not isinstance(prompt, str):
        raise ValueError("Incomplete Desktop hook input")
    with AppServerReader(cwd) as app:
        thread = app.call(
            "thread/read", {"threadId": session_id, "includeTurns": False}, 10
        )["thread"]
        effort = thread.get("reasoningEffort")
        if thread.get("model") != model or not isinstance(effort, str):
            raise ValueError("Active model or reasoning effort is unavailable")
        turns = []
        cursor = None
        seen_cursors = set()
        for _ in range(CONTEXT_PAGE_LIMIT):
            params = {
                "threadId": session_id,
                "limit": TURN_PAGE_LIMIT,
                "itemsView": "summary",
            }
            if cursor is not None:
                params["cursor"] = cursor
            page = app.call("thread/turns/list", params, 10)
            turns.extend(page.get("data", []))
            cursor = page.get("nextCursor")
            if cursor is None:
                break
            if cursor in seen_cursors:
                raise ValueError("Conversation context pagination repeated a cursor")
            seen_cursors.add(cursor)
        current_index = (
            next(
                (
                    index
                    for index, turn in enumerate(turns)
                    if turn.get("id") == event.get("turn_id")
                ),
                None,
            )
            if event.get("turn_id") is not None
            else None
        )
        if current_index is not None:
            turns = turns[current_index + 1 :]
        deadline = time.monotonic() + INPUT_SCAN_TIMEOUT_SECONDS
        for turn in turns[:CONTEXT_TURN_LIMIT]:
            if not turn.get("id") or any(
                (item.get("type") == "userMessage" for item in turn.get("items", []))
            ):
                continue
            items = []
            cursor = None
            seen = set()
            for _ in range(MAX_INPUT_PAGES):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Native working context read timed out")
                result = app.call(
                    "thread/items/list",
                    {
                        "threadId": session_id,
                        "turnId": turn["id"],
                        "limit": QUEUE_PAGE_LIMIT,
                        **({"cursor": cursor} if cursor else {}),
                    },
                    min(RPC_TIMEOUT_SECONDS, remaining),
                )
                items.extend((entry["item"] for entry in result["data"]))
                cursor = result.get("nextCursor")
                if cursor is None:
                    break
                if cursor in seen:
                    raise ValueError("Native working context repeated a cursor")
                seen.add(cursor)
            else:
                raise ValueError(
                    "Native working context pagination exceeded the supported bound"
                )
            turn["items"] = [
                item for item in items if item.get("type") == "functionCallOutput"
            ] + turn.get("items", [])
    request = {
        "task": prompt
        or "Запрос с вложениями без текстового описания; учитывай контекст текущей работы.",
        "active_profile": {"model": model, "effort": effort, "speed": None},
    }
    context = recent_context(prompt, turns, event.get("turn_id"), CONTROL_PROMPT)
    if context is not None:
        request["context"] = context
    return request
