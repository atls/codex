from urllib.parse import urlparse
from model_fit.application.assessment.exceptions.unknown_speed_change import (
    UnknownSpeedChange,
)
from model_fit.application.assessment.types.catalog import ProfileCatalog
from model_fit.application.assessment.decoding import decode_decision
from model_fit.application.assessment.types.profile import ActiveProfile
from model_fit.application.assessment.types.decision import (
    AssessmentDecision,
)

RECOMMENDATIONS = {"recommend_lighter", "recommend_stronger", "recommend_faster"}

DECISIONS = {
    "keep",
    "recommend_lighter",
    "recommend_stronger",
    "recommend_faster",
    "unknown",
}

EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def official_source(url: object) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "developers.openai.com"
        and (
            parsed.path.rstrip("/").removesuffix(".md")
            in ("/api/docs/guides/model-selection", "/api/docs/guides/reasoning")
        )
    )


def validate(
    output: object, active: ActiveProfile, models: ProfileCatalog
) -> AssessmentDecision:
    current_fields = dict(active)
    result = decode_decision(output)
    observed = dict(result)
    for field in ("model", "effort", "speed"):
        if observed[f"active_{field}"] != current_fields[field]:
            raise ValueError(f"Preflight changed active_{field}")
    if not result["reason"].strip():
        raise ValueError("Preflight reason is empty")
    decision = result["decision"]
    fields = ("model", "effort", "speed")
    proposed = {
        "model": result["recommended_model"],
        "effort": result["recommended_effort"],
        "speed": result["recommended_speed"],
    }
    if any(
        (
            value is not None and (not isinstance(value, str) or not value.strip())
            for value in proposed.values()
        )
    ):
        raise ValueError("Recommendation contains an empty profile field")
    if decision in ("keep", "unknown"):
        if any(
            (proposed[field] not in (None, current_fields[field]) for field in fields)
        ):
            raise ValueError("Non-recommendation contains a changed profile")
        result["recommended_model"] = None
        result["recommended_effort"] = None
        result["recommended_speed"] = None
        if decision == "keep":
            result["official_source_url"] = None
            result["official_guidance"] = None
            result["task_inference"] = None
        return result
    if not official_source(result.get("official_source_url")):
        raise ValueError("Recommendation lacks a supported official source")
    guidance = result.get("official_guidance")
    inference = result.get("task_inference")
    if not isinstance(guidance, str) or not guidance.strip():
        raise ValueError("Official guidance is empty")
    if (
        not isinstance(inference, str)
        or not inference.strip()
        or inference.strip() == guidance.strip()
    ):
        raise ValueError("Task inference is missing or duplicates guidance")
    target: ActiveProfile = {
        "model": proposed["model"] or active["model"],
        "effort": proposed["effort"] or active["effort"],
        "speed": proposed["speed"] or active["speed"],
    }
    if target == active:
        raise ValueError("Recommendation does not change the active profile")
    if active["speed"] is None and proposed["speed"] is not None:
        raise UnknownSpeedChange("Cannot recommend a speed change from unknown speed")
    if not models.supported(target):
        raise ValueError("Recommendation target is not in the supplied catalog")
    if target["model"] == active["model"] and decision in (
        "recommend_lighter",
        "recommend_stronger",
    ):
        if active["effort"] not in EFFORT_ORDER or target["effort"] not in EFFORT_ORDER:
            raise ValueError("Cannot compare unknown reasoning effort")
        current_rank = EFFORT_ORDER.index(active["effort"])
        target_rank = EFFORT_ORDER.index(target["effort"])
        if (
            decision == "recommend_lighter"
            and target_rank >= current_rank
            or (decision == "recommend_stronger" and target_rank <= current_rank)
        ):
            raise ValueError("Recommendation contradicts reasoning effort direction")
    if decision == "recommend_faster" and (
        target["model"] != active["model"]
        or target["effort"] != active["effort"]
        or target["speed"] == active["speed"]
    ):
        raise ValueError("Faster recommendation changes the quality profile")
    if decision in ("recommend_lighter", "recommend_stronger") and (
        target["model"] == active["model"] and target["effort"] == active["effort"]
    ):
        raise ValueError("Quality recommendation changes only speed")
    return result
