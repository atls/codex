"""Preserve and verify complete native user input across queued turns."""

from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
from typing import Any
from model_fit.app_server import AppServerReader

QUEUE_PAGE_LIMIT = 100
MAX_INPUT_PAGES = 5
RPC_TIMEOUT_SECONDS = 10


def prompt_digest(prompt: str) -> str:
    return sha256(prompt.encode()).hexdigest()


def replay_prompt(prompt: str, nonce: str) -> str:
    return f"{prompt}\n\n<!-- model-fit-replay:{nonce} -->"


def input_text(content: list[dict[str, Any]]) -> str:
    return "\n".join(item["text"] for item in content if item.get("type") == "text")


def input_digest(content: list[dict[str, Any]]) -> str:
    return sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def source_input(
    app: AppServerReader, thread_id: str, turn_id: str
) -> list[dict[str, Any]]:
    cursor = None
    seen_cursors: set[str] = set()
    for _ in range(MAX_INPUT_PAGES):
        params: dict[str, Any] = {
            "threadId": thread_id,
            "turnId": turn_id,
            "limit": QUEUE_PAGE_LIMIT,
        }
        if cursor is not None:
            params["cursor"] = cursor
        result = app.call("thread/items/list", params, RPC_TIMEOUT_SECONDS)
        for entry in result["data"]:
            item = entry["item"]
            if item.get("type") == "userMessage":
                content = item.get("content")
                if (
                    not isinstance(content, list)
                    or not content
                    or not all(isinstance(value, dict) for value in content)
                ):
                    raise ValueError("Source user input is unavailable")
                return content
        cursor = result.get("nextCursor")
        if cursor is None:
            break
        if cursor in seen_cursors:
            raise ValueError("Source input pagination repeated a cursor")
        seen_cursors.add(cursor)
    raise ValueError("Source user input is unavailable within the bounded scan")


def replay_input(content: list[dict[str, Any]], nonce: str) -> list[dict[str, Any]]:
    replay = deepcopy(content)
    for item in reversed(replay):
        if item.get("type") == "text":
            item["text"] = replay_prompt(item["text"], nonce)
            return replay
    replay.append(
        {"type": "text", "text": replay_prompt("", nonce), "text_elements": []}
    )
    return replay


def queue_input_matches(
    requested: list[dict[str, Any]], received: list[dict[str, Any]]
) -> bool:
    if len(requested) != len(received):
        return False
    for original, queued in zip(requested, received):
        if original == queued:
            continue
        if original.get("type") != "localImage" or queued.get("type") != "image":
            return False
        url = queued.get("url")
        if (
            not isinstance(url, str)
            or not url.startswith("data:image/")
            or ";base64," not in url
        ):
            return False
        if not url.split(";base64,", 1)[1]:
            return False
        expected = dict(original)
        expected.pop("path")
        expected.update(type="image", url=url)
        if expected != queued:
            return False
    return True
