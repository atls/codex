from model_fit.assessment.types.decision import AssessmentDecision, DecisionKind


def decision_kind(value: object) -> DecisionKind:
    match value:
        case (
            "keep"
            | "unknown"
            | "recommend_lighter"
            | "recommend_stronger"
            | "recommend_faster"
        ):
            return value
        case _:
            raise ValueError("Unknown preflight decision")


def required_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Decision text must be a string")
    return value


def optional_text(value: object) -> str | None:
    if value is None:
        return None
    return required_text(value)


def decode_decision(value: object) -> AssessmentDecision:
    if not isinstance(value, dict):
        raise ValueError("Preflight result is not an object")
    return {
        "active_model": required_text(value["active_model"]),
        "active_effort": required_text(value["active_effort"]),
        "active_speed": optional_text(value["active_speed"]),
        "decision": decision_kind(value["decision"]),
        "recommended_model": optional_text(value["recommended_model"]),
        "recommended_effort": optional_text(value["recommended_effort"]),
        "recommended_speed": optional_text(value["recommended_speed"]),
        "official_source_url": optional_text(value["official_source_url"]),
        "official_guidance": optional_text(value["official_guidance"]),
        "task_inference": optional_text(value["task_inference"]),
        "reason": required_text(value["reason"]),
    }
