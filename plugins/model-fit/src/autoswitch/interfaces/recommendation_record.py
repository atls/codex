from typing import TypedDict

from model_fit.assessment.interfaces.decision import AssessmentDecision
from model_fit.assessment.interfaces.profile import ActiveProfile


class RecommendationRecord(TypedDict):
    prompt_hash: str
    active_profile: ActiveProfile
    result: AssessmentDecision
