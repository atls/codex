from vector_prime.application.assessment.types.recommendation import (
    RecommendationRecord,
)
from vector_prime.application.assessment.request import (
    validated_active_profile,
)
from vector_prime.application.assessment.guards.recommendation import (
    require_recommendation,
)


def require_blocking_record(cached: RecommendationRecord) -> None:
    if (
        len(cached["prompt_hash"]) != 64
        or len(bytes.fromhex(cached["prompt_hash"])) != 32
        or cached["prompt_hash"] != cached["prompt_hash"].lower()
    ):
        raise ValueError("Blocking recommendation input hash is invalid")
    active = validated_active_profile({"active_profile": cached["active_profile"]})
    if (
        not active["model"]
        or not active["effort"]
        or not {"active_model", "active_effort", "active_speed"}.issubset(
            cached["result"]
        )
        or cached["result"].get("active_model") != active["model"]
        or cached["result"].get("active_effort") != active["effort"]
        or cached["result"].get("active_speed") != active["speed"]
    ):
        raise ValueError("Blocking recommendation profile is inconsistent")
    require_recommendation(cached["result"])
