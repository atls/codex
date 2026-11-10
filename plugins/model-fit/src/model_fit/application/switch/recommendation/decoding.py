from model_fit.application.assessment.decoding import (
    decision_kind,
    optional_text,
    required_text,
)
from model_fit.application.switch.recommendation.types.evidence import (
    RecommendationEvidence,
)


def decode_evidence(value: object) -> RecommendationEvidence:
    if not isinstance(value, dict):
        raise ValueError("Pending recommendation is not an object")
    result: RecommendationEvidence = {
        "decision": decision_kind(value["decision"]),
    }
    if "active_model" in value:
        result["active_model"] = required_text(value["active_model"])
    if "active_effort" in value:
        result["active_effort"] = required_text(value["active_effort"])
    if "active_speed" in value:
        result["active_speed"] = optional_text(value["active_speed"])
    if "recommended_model" in value:
        result["recommended_model"] = optional_text(value["recommended_model"])
    if "recommended_effort" in value:
        result["recommended_effort"] = optional_text(value["recommended_effort"])
    if "recommended_speed" in value:
        result["recommended_speed"] = optional_text(value["recommended_speed"])
    if "official_source_url" in value:
        result["official_source_url"] = optional_text(value["official_source_url"])
    if "official_guidance" in value:
        result["official_guidance"] = optional_text(value["official_guidance"])
    if "task_inference" in value:
        result["task_inference"] = optional_text(value["task_inference"])
    if "reason" in value:
        result["reason"] = required_text(value["reason"])
    return result
