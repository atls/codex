from model_fit.application.assessment.types.decision import (
    AssessmentDecision,
)
from model_fit.application.assessment.types.work_relation import WorkRelation
from model_fit.application.assessment.types.profile import ActiveProfile
from model_fit.application.submission.types.json import JsonValue
from model_fit.application.submission.constraints.content import checked_object
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
