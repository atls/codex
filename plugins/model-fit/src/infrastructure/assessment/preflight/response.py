import json
from pathlib import Path
from typing import Any


def assessment_response(
    events: list[dict[str, Any]], skill_file: Path, diagnostics: dict[str, Any] | None
) -> dict[str, Any]:
    messages = []
    tool_types = []
    skill_item_seen = False
    for event in events:
        item = (event.get("params") or {}).get("item") or {}
        if (
            event.get("method") == "item/completed"
            and item.get("type") == "agentMessage"
        ):
            messages.append(item.get("text") or "")
        if (
            event.get("method") == "item/completed"
            and item.get("type") == "userMessage"
        ):
            skill_item_seen = skill_item_seen or any(
                content.get("type") == "skill"
                and content.get("name") == "model-fit"
                and content.get("path") == str(skill_file)
                for content in item.get("content", [])
            )
        if event.get("method") == "item/started" and item.get("type") not in (
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
                raise RuntimeError("Preflight attempted a task tool")
    if not messages:
        raise RuntimeError("Preflight returned no decision")
    if not skill_item_seen:
        raise RuntimeError("Preflight skill input was not observed")
    if diagnostics is not None:
        diagnostics["agent_messages"] = len(messages)
        diagnostics["skill_item_seen"] = skill_item_seen
        diagnostics["tool_types"] = tool_types
    output = json.loads(messages[-1])
    if not isinstance(output, dict):
        raise ValueError("Preflight decision is not an object")
    return output
