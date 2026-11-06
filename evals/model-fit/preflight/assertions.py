"""Confirm native Model Fit skill input independently of decision validation."""

import json


def get_assert(output, context):
    try:
        raw = json.loads(context["providerResponse"]["raw"])
        expected = context["vars"]["skill_file"]
        if not isinstance(expected, str) or not expected:
            raise ValueError("Expected skill path is unavailable")
        items = raw.get("items")
        if items is None:
            items = []
        if not isinstance(items, list):
            raise ValueError("Native items must be an array")
        found = any(
            isinstance(item, dict)
            and item.get("type") == "user_message"
            and isinstance(item.get("content"), list)
            and any(
                isinstance(entry, dict)
                and entry.get("type") == "skill"
                and entry.get("name") == "model-fit"
                and entry.get("path") == expected
                for entry in item["content"]
            )
            for item in items
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"pass": False, "score": 0, "reason": "Native events unavailable"}
    return {
        "pass": found,
        "score": 1 if found else 0,
        "reason": "Native skill input confirmed"
        if found
        else "Native skill input not confirmed",
    }
