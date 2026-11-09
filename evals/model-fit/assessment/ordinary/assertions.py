"""Check ordinary dialogue without tools or profile-selection advice."""

import json
import re

PROFILE_ADVICE = re.compile(
    "model[ -]fit|gpt-|luna|astra|reasoning[_ ]effort|profile (?:change|switch)|смен[аыу] профил",
    re.IGNORECASE,
)


def get_assert(output, context):
    try:
        raw = json.loads(context["providerResponse"]["raw"])
        items = raw.get("items")
        if items is None:
            items = []
        if not isinstance(items, list):
            raise ValueError("Native items must be an array")
        tools = [
            item
            for item in items
            if item.get("type") not in {"user_message", "agent_message", "reasoning"}
        ]
        passed = not tools and PROFILE_ADVICE.search(output) is None
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"pass": False, "score": 0, "reason": "Native events unavailable"}
    return {
        "pass": passed,
        "score": 1 if passed else 0,
        "reason": "Ordinary dialogue did not invoke tools or profile selection"
        if passed
        else "Unexpected tool or profile selection in ordinary dialogue",
    }
