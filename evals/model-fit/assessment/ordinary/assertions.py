"""Require a valid tool-free trace; the configured rubric grades response semantics."""

import json


def get_assert(output, context):
    try:
        raw = json.loads(context["providerResponse"]["raw"])
        items = raw.get("items")
        if not isinstance(items, list):
            raise ValueError("Native items must be an array")
        tools = [
            item
            for item in items
            if item.get("type") not in {"user_message", "agent_message", "reasoning"}
        ]
        passed = not tools
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"pass": False, "score": 0, "reason": "Native events unavailable"}
    return {
        "pass": passed,
        "score": 1 if passed else 0,
        "reason": "Native trace contains no tools; response semantics are graded separately"
        if passed
        else "Unexpected native tool activity in ordinary dialogue",
    }
