"""Project native Codex events into test observations."""

from __future__ import annotations
from pathlib import Path
from typing import Any


def observe(events: list[dict[str, Any]], skill_file: Path) -> dict[str, Any]:
    messages = []
    tool_types = []
    task_tool_seen = False
    usage = None
    skill_item_seen = False
    for event in events:
        method = event.get("method")
        params = event.get("params") or {}
        item = params.get("item") or {}
        if method == "item/completed" and item.get("type") == "agentMessage":
            messages.append(item.get("text") or "")
        if method == "item/completed" and item.get("type") == "userMessage":
            skill_item_seen = skill_item_seen or any(
                content.get("type") == "skill"
                and content.get("name") == "model-fit"
                and content.get("path") == str(skill_file)
                for content in item.get("content", [])
            )
        if method == "item/started" and item.get("type") not in (
            "agentMessage",
            "userMessage",
            "reasoning",
        ):
            tool_types.append(item.get("type"))
            actions = item.get("commandActions") or []
            if (
                item.get("type") != "commandExecution"
                or not actions
                or any(
                    action.get("type") not in ("read", "listFiles", "search")
                    for action in actions
                )
            ):
                task_tool_seen = True
        if method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage")
    return {
        "messages": messages,
        "tool_types": tool_types,
        "usage": usage,
        "skill_item_seen": skill_item_seen,
        "task_tool_seen": task_tool_seen,
    }
