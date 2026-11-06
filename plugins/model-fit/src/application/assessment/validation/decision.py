from typing import Any
from urllib.parse import urlparse

from model_fit.application.assessment.ports.catalog import Catalog

RECOMMENDATIONS = {"recommend_lighter", "recommend_stronger", "recommend_faster"}

DECISIONS = {
    "keep",
    "recommend_lighter",
    "recommend_stronger",
    "recommend_faster",
    "unknown",
}

EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def official_source(url: Any) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "developers.openai.com"
        and parsed.path.rstrip("/").removesuffix(".md")
        in ("/api/docs/guides/model-selection", "/api/docs/guides/reasoning")
    )


def validate(
    output: dict[str, Any], active: dict[str, Any], models: Catalog
) -> dict[str, Any]:
    expected_fields = {
        "active_model",
        "active_effort",
        "active_speed",
        "decision",
        "recommended_model",
        "recommended_effort",
        "recommended_speed",
        "official_source_url",
        "official_guidance",
        "task_inference",
        "reason",
    }
    if set(output) != expected_fields:
        raise ValueError("Preflight result does not match the decision schema")
    if output.get("decision") not in DECISIONS:
        raise ValueError("Unknown preflight decision")
    for field in ("model", "effort", "speed"):
        if output.get(f"active_{field}") != active[field]:
            raise ValueError(f"Preflight changed active_{field}")
    if not isinstance(output.get("reason"), str) or not output["reason"].strip():
        raise ValueError("Preflight reason is empty")
    result = dict(output)
    decision = result["decision"]
    fields = ("model", "effort", "speed")
    proposed = {field: result.get(f"recommended_{field}") for field in fields}
    if any(
        value is not None and (not isinstance(value, str) or not value.strip())
        for value in proposed.values()
    ):
        raise ValueError("Recommendation contains an empty profile field")
    if decision in ("keep", "unknown"):
        if any(proposed[field] not in (None, active[field]) for field in fields):
            raise ValueError("Non-recommendation contains a changed profile")
        for field in fields:
            result[f"recommended_{field}"] = None
        if decision == "keep":
            for field in ("official_source_url", "official_guidance", "task_inference"):
                result[field] = None
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
    target = {field: proposed[field] or active[field] for field in fields}
    if target == active:
        raise ValueError("Recommendation does not change the active profile")
    if active["speed"] is None and proposed["speed"] is not None:
        raise ValueError("Cannot recommend a speed change from unknown speed")
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
            or decision == "recommend_stronger"
            and target_rank <= current_rank
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


def empty_decision(
    active: dict[str, Any], decision: str, reason: str
) -> dict[str, Any]:
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
