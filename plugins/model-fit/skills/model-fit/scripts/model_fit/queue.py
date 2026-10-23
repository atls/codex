"""Read native queue and turn completion without changing their state."""

from __future__ import annotations
from typing import Any
from model_fit.app_server import AppServerReader
from model_fit.input import input_digest, prompt_digest, input_text

QUEUE_PAGE_LIMIT = 100
MAX_QUEUE_PAGES = 5
RPC_TIMEOUT_SECONDS = 10
TURN_PAGE_LIMIT = 5
TERMINAL_TURN_STATUSES = {"completed", "failed", "interrupted"}


def queued_ids(app: AppServerReader, thread_id: str) -> set[str]:
    ids: set[str] = set()
    cursor = None
    seen_cursors: set[str] = set()
    for _ in range(MAX_QUEUE_PAGES):
        params: dict[str, Any] = {"threadId": thread_id, "limit": QUEUE_PAGE_LIMIT}
        if cursor is not None:
            params["cursor"] = cursor
        result = app.call("thread/queue/list", params, RPC_TIMEOUT_SECONDS)
        ids.update(item["id"] for item in result["data"])
        cursor = result.get("nextCursor")
        if cursor is None:
            return ids
        if cursor in seen_cursors:
            raise ValueError("Queue pagination repeated a cursor")
        seen_cursors.add(cursor)
    raise ValueError("Queue exceeds the bounded Model Fit scan")


def replay_finished(
    app: AppServerReader, thread_id: str, state: dict[str, Any]
) -> bool:
    result = app.call(
        "thread/turns/list",
        {
            "threadId": thread_id,
            "limit": TURN_PAGE_LIMIT,
            "itemsView": "summary",
        },
        RPC_TIMEOUT_SECONDS,
    )
    for turn in result["data"]:
        started_at = turn.get("startedAt")
        if isinstance(started_at, int) and started_at < state["queued_at"]:
            return False
        replay_turn_id = state.get("replay_turn_id")
        if replay_turn_id is not None:
            if turn.get("id") == replay_turn_id:
                return turn.get("status") in TERMINAL_TURN_STATUSES
            continue
        if (
            not isinstance(started_at, int)
            or turn.get("id") == state["source_turn_id"]
            or turn.get("status") not in TERMINAL_TURN_STATUSES
        ):
            continue
        items = app.call(
            "thread/items/list",
            {
                "threadId": thread_id,
                "turnId": turn["id"],
                "limit": 10,
            },
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


def source_interrupted(
    app: AppServerReader, thread_id: str, source_turn_id: str
) -> bool:
    turns = app.call(
        "thread/turns/list",
        {
            "threadId": thread_id,
            "limit": TURN_PAGE_LIMIT,
            "itemsView": "summary",
        },
        RPC_TIMEOUT_SECONDS,
    )["data"]
    return any(
        turn.get("id") == source_turn_id and turn.get("status") == "interrupted"
        for turn in turns
    )
