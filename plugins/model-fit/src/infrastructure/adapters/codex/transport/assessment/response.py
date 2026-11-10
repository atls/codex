import json
from pathlib import Path
from model_fit.native_input.validation import (
    checked_object,
    checked_content,
    native_text,
)
from model_fit.native_input.types.json import JsonValue


def assessment_response(
    events: list[dict[str, JsonValue]],
    skill_file: Path,
    diagnostics: dict[str, JsonValue] | None,
) -> dict[str, JsonValue]:
    messages: list[str] = []
    tool_types: list[JsonValue] = []
    skill_item_seen = False
    for event in events:
        params = checked_object(event.get("params") or {})
        item = checked_object(params.get("item") or {})
        if (
            event.get("method") == "item/completed"
            and item.get("type") == "agentMessage"
        ):
            messages.append(native_text(item.get("text") or ""))
        if (
            event.get("method") == "item/completed"
            and item.get("type") == "userMessage"
        ):
            skill_item_seen = skill_item_seen or any(
                (
                    content.get("type") == "skill"
                    and content.get("name") == "model-fit"
                    and (content.get("path") == str(skill_file))
                    for content in checked_content(item.get("content", []))
                )
            )
        if event.get("method") == "item/started" and item.get("type") not in (
            "agentMessage",
            "userMessage",
            "reasoning",
        ):
            tool_types.append(item.get("type"))
            actions = checked_content(item.get("commandActions") or [])
            if (
                item.get("type") != "commandExecution"
                or not actions
                or any(
                    (
                        action.get("type") not in ("read", "listFiles", "search")
                        for action in actions
                    )
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
    return checked_object(output)
