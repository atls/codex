import hashlib
import json

from model_fit.application.assessment.types.request import ProfileAssessmentInput
from model_fit.application.submission.types.json import JsonValue


def record_user_choice(
    diagnostics: dict[str, JsonValue] | None, request: ProfileAssessmentInput
) -> None:
    if diagnostics is not None:
        diagnostics.update(
            {
                "prompt_sha256": hashlib.sha256(
                    json.dumps(request, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
                "user_choice_bypass": True,
                "agent_messages": 0,
                "skill_item_seen": False,
                "tool_types": [],
                "events": [{"event": "confirmed_user_choice_bypass"}],
                "usage": None,
            }
        )
