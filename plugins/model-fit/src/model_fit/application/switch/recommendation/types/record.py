from typing import NotRequired, TypedDict

from model_fit.application.switch.recommendation.types.evidence import (
    RecommendationEvidence,
)
from model_fit.application.assessment.types.profile import ActiveProfile


class RecommendationRecord(TypedDict):
    prompt_hash: str
    active_profile: ActiveProfile
    result: RecommendationEvidence
    assessment_hash: NotRequired[str]
