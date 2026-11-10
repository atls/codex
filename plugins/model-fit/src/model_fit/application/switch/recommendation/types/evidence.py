from typing import NotRequired, TypedDict
from model_fit.application.assessment.types.decision import DecisionKind


class RecommendationEvidence(TypedDict):
    active_model: NotRequired[str]
    active_effort: NotRequired[str]
    active_speed: NotRequired[str | None]
    decision: DecisionKind
    recommended_model: NotRequired[str | None]
    recommended_effort: NotRequired[str | None]
    recommended_speed: NotRequired[str | None]
    official_source_url: NotRequired[str | None]
    official_guidance: NotRequired[str | None]
    task_inference: NotRequired[str | None]
    reason: NotRequired[str]
