from typing import NotRequired, TypedDict

from model_fit.autoswitch.recommendation.types.evidence import RecommendationEvidence
from model_fit.assessment.types.profile import ActiveProfile


class RecommendationRecord(TypedDict):
    prompt_hash: str
    active_profile: ActiveProfile
    result: RecommendationEvidence
    assessment_hash: NotRequired[str]
