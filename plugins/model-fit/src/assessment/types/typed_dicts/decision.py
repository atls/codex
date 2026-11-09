from typing import TypedDict

from model_fit.assessment.types.aliases.decision_kind import DecisionKind


class AssessmentDecision(TypedDict):
    active_model: str
    active_effort: str
    active_speed: str | None
    decision: DecisionKind
    recommended_model: str | None
    recommended_effort: str | None
    recommended_speed: str | None
    official_source_url: str | None
    official_guidance: str | None
    task_inference: str | None
    reason: str
