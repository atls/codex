from typing import Literal, TypedDict

from vector_prime.application.submission.types.json import JsonValue


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
