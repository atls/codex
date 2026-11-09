from typing import TypedDict

from model_fit.assessment.decision import AssessmentDecision
from model_fit.assessment.profile import ActiveProfile


class RecommendationRecord(TypedDict):
    prompt_hash: str
    active_profile: ActiveProfile
    result: AssessmentDecision
