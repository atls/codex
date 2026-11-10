from typing import Literal, TypedDict

from model_fit.native_input.types.json import JsonValue


class HookSpecificOutput(TypedDict, total=False):
    hookEventName: Literal["UserPromptSubmit", "PreToolUse"]
    additionalContext: str
    permissionDecision: Literal["allow", "deny"]
    permissionDecisionReason: str
    updatedInput: dict[str, JsonValue]


class HookOutput(TypedDict, total=False):
    decision: Literal["block"]
    reason: str
    systemMessage: str
    hookSpecificOutput: HookSpecificOutput
