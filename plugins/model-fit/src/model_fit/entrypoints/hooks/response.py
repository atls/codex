from __future__ import annotations

from model_fit.application.assessment.types.decision import AssessmentDecision
from model_fit.application.switch.recommendation.types.evidence import (
    RecommendationEvidence,
)

from model_fit.application.switch.handoff.control_message import CONTROL_PROMPTS

"""Render Model Fit outcomes as native hook responses."""


from model_fit.entrypoints.hooks.types.output import HookOutput
from model_fit.application.submission.types.json import JsonValue

from model_fit.application.assessment.constraints.decision import RECOMMENDATIONS
from model_fit.application.switch.recommendation.validation import (
    require_recommendation,
)
from model_fit.entrypoints.hooks.instructions import (
    UNKNOWN_CONTEXT,
    admission_unavailable_context,
    inactive_context,
)
from model_fit.entrypoints.hooks.native_contract import PROFILE_SWITCH_TOOLS


def inactive_hook(
    event: dict[str, JsonValue],
    *,
    unavailable: bool = False,
    admitted_tool: bool = False,
) -> HookOutput | None:
    if event.get("hook_event_name") == "UserPromptSubmit":
        return admission_unavailable_context() if unavailable else inactive_context()
    if unavailable:
        if event.get("hook_event_name") == "PreToolUse":
            if admitted_tool:
                return None
            return deny_tool(
                "Model Fit: current hook authorization is unavailable; previous restrictions remain in effect. No automatic handoff occurred."
            )
        if event.get("hook_event_name") == "Stop" and (
            not event.get("stop_hook_active")
        ):
            return {
                "systemMessage": "Model Fit: current hook authorization is unavailable; suitability of the active profile is unconfirmed."
            }
    arguments = event.get("tool_input")
    if (
        event.get("hook_event_name") == "PreToolUse"
        and event.get("tool_name") in PROFILE_SWITCH_TOOLS
        and isinstance(arguments, dict)
        and (arguments.get("prompt") in CONTROL_PROMPTS)
    ):
        return deny_tool(
            "Model Fit: automatic handoff is not authorized. Do not repeat technical profile switching while authorization is disabled or unknown."
        )
    return None


def unknown(message: str | None = None) -> HookOutput:
    return {"systemMessage": (message + " " if message else "") + UNKNOWN_CONTEXT}


def hook_output(
    result: AssessmentDecision | RecommendationEvidence,
) -> HookOutput | None:
    decision = result["decision"]
    if decision == "keep":
        return None
    if decision == "unknown":
        return unknown()
    if decision not in RECOMMENDATIONS:
        raise ValueError("Unsupported triage decision")
    require_recommendation(result)
    model = result.get("recommended_model") or result["active_model"]
    effort = result.get("recommended_effort") or result["active_effort"]
    source = result.get("official_source_url")
    guidance = result.get("official_guidance")
    inference = result.get("task_inference")
    return {
        "decision": "block",
        "reason": f"Model Fit: switch the profile to {model} / {effort} and repeat this request. OpenAI guidance: {guidance} Task-specific conclusion: {inference} Source: {source}",
    }


def deny_tool(reason: str) -> HookOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def allow_tool(updated_input: dict[str, JsonValue]) -> HookOutput:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": updated_input,
        }
    }
