"Render Model Fit outcomes as native hook responses."

from __future__ import annotations

from typing import Any

from model_fit.assessment.validation import RECOMMENDATIONS
from model_fit.entrypoints.hooks.configuration import PROFILE_SWITCH_TOOLS
from model_fit.entrypoints.hooks.instructions import (
    CONTROL_PROMPT,
    UNKNOWN_CONTEXT,
    admission_unavailable_context,
    inactive_context,
)


def inactive_hook(
    event: dict[str, Any], *, unavailable: bool = False, admitted_tool: bool = False
) -> dict[str, Any] | None:
    if event.get("hook_event_name") == "UserPromptSubmit":
        return admission_unavailable_context() if unavailable else inactive_context()
    if unavailable:
        if event.get("hook_event_name") == "PreToolUse":
            if admitted_tool:
                return None
            return deny_tool(
                "Model Fit: актуальное разрешение hooks недоступно; прежние ограничения не сняты. Автоматический перенос не выполнялся."
            )
        if event.get("hook_event_name") == "Stop" and (
            not event.get("stop_hook_active")
        ):
            return {
                "systemMessage": "Model Fit: актуальное разрешение hooks недоступно; пригодность текущего профиля не подтверждена."
            }
    arguments = event.get("tool_input")
    if (
        event.get("hook_event_name") == "PreToolUse"
        and event.get("tool_name") in PROFILE_SWITCH_TOOLS
        and isinstance(arguments, dict)
        and (arguments.get("prompt") == CONTROL_PROMPT)
    ):
        return deny_tool(
            "Model Fit: разрешение автоматического переноса отсутствует. Не повторяй техническую смену профиля при отключённом или неизвестном разрешении."
        )
    return None


def unknown(message: str | None = None) -> dict[str, Any]:
    return {"systemMessage": (message + " " if message else "") + UNKNOWN_CONTEXT}


def hook_output(result: dict[str, Any]) -> dict[str, Any] | None:
    decision = result["decision"]
    if decision == "keep":
        return None
    if decision == "unknown":
        return unknown()
    if decision not in RECOMMENDATIONS:
        raise ValueError("Unsupported triage decision")
    model = result.get("recommended_model") or result["active_model"]
    effort = result.get("recommended_effort") or result["active_effort"]
    source = result.get("official_source_url")
    guidance = result.get("official_guidance")
    inference = result.get("task_inference")
    if not all(
        (
            isinstance(value, str) and value
            for value in (model, effort, source, guidance, inference)
        )
    ):
        raise ValueError("Incomplete triage recommendation")
    return {
        "decision": "block",
        "reason": f"Model Fit: переключи профиль на {model} / {effort} и повтори этот запрос. Рекомендация OpenAI: {guidance} Вывод для этой задачи: {inference} Источник: {source}",
    }


def deny_tool(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def allow_tool(updated_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": updated_input,
        }
    }
