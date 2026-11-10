from model_fit.application.assessment.types.profile import ActiveProfile
from model_fit.application.assessment.types.decision import (
    AssessmentDecision,
    DecisionKind,
)


def empty_decision(
    active: ActiveProfile, decision: DecisionKind, reason: str
) -> AssessmentDecision:
    return {
        "active_model": active["model"],
        "active_effort": active["effort"],
        "active_speed": active["speed"],
        "decision": decision,
        "recommended_model": None,
        "recommended_effort": None,
        "recommended_speed": None,
        "official_source_url": None,
        "official_guidance": None,
        "task_inference": None,
        "reason": reason,
    }
