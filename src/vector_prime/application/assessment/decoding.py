from vector_prime.application.assessment.types.user_choice import RetainedProfileChoice
from vector_prime.application.assessment.types.decision import (
    AssessmentDecision,
)
from vector_prime.application.assessment.types.work_relation import WorkRelation
from vector_prime.application.assessment.types.profile import ActiveProfile
from vector_prime.application.submission.types.json import JsonValue
from vector_prime.application.submission.decoding import checked_object
from pydantic import TypeAdapter, ValidationError


DECISION_ADAPTER = TypeAdapter(AssessmentDecision)
PROFILE_ADAPTER = TypeAdapter(ActiveProfile)


def decode_evaluation(value: object) -> tuple[WorkRelation, dict[str, JsonValue]]:
    evaluation = checked_object(value)
    relation = WorkRelation(required_text(evaluation.get("work_relation")))
    return relation, {
        key: item for key, item in evaluation.items() if key != "work_relation"
    }


def required_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Decision text must be a string")
    return value


def optional_text(value: object) -> str | None:
    if value is None:
        return None
    return required_text(value)


def decode_decision(value: object) -> AssessmentDecision:
    try:
        return DECISION_ADAPTER.validate_python(value, strict=True)
    except ValidationError:
        raise ValueError(
            "Preflight result does not match the decision schema"
        ) from None


def decode_profile(value: object) -> ActiveProfile:
    try:
        return PROFILE_ADAPTER.validate_python(value, strict=True)
    except ValidationError:
        raise ValueError("Active profile fields are invalid or incomplete") from None


def decode_retained_choice(value: object) -> RetainedProfileChoice:
    if (
        not isinstance(value, dict)
        or set(value) != {"user_selected", "same_work", "profile"}
        or value["user_selected"] is not True
        or value["same_work"] is not True
    ):
        raise ValueError("prior_choice does not confirm this active profile and work")
    return {
        "user_selected": True,
        "same_work": True,
        "profile": decode_profile(value["profile"]),
    }
