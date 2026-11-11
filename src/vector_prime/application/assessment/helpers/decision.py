from vector_prime.application.assessment.types.recommendation import (
    RecommendationRecord,
)
from vector_prime.application.assessment.types.profile import ActiveProfile
from vector_prime.application.assessment.types.decision import (
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


def recommended_profile(pending: RecommendationRecord) -> ActiveProfile:
    active = pending["active_profile"]
    result = pending["result"]
    return {
        "model": result.get("recommended_model") or active["model"],
        "effort": result.get("recommended_effort") or active["effort"],
        "speed": result.get("recommended_speed") or active["speed"],
    }
