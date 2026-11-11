from vector_prime.application.assessment.decoding import decode_decision
from vector_prime.application.assessment.guards.decision import (
    require_consistent_decision,
)
from vector_prime.application.assessment.helpers.decision import (
    normalize_unchanged_decision,
)
from vector_prime.application.assessment.types.catalog import ProfileCatalog
from vector_prime.application.assessment.types.decision import AssessmentDecision
from vector_prime.application.assessment.types.profile import ActiveProfile

RECOMMENDATIONS = {"recommend_lighter", "recommend_stronger", "recommend_faster"}


def validate(
    output: object, active: ActiveProfile, models: ProfileCatalog
) -> AssessmentDecision:
    result = decode_decision(output)
    require_consistent_decision(result, active, models)
    if result["decision"] in {"keep", "unknown"}:
        return normalize_unchanged_decision(result)
    return result
