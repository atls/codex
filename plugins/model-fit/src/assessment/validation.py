from urllib.parse import urlparse

from model_fit.assessment.exceptions.unknown_speed_change import UnknownSpeedChange
from model_fit.assessment.types.catalog import ProfileCatalog
from model_fit.assessment.decoding import decode_decision
from model_fit.assessment.types.profile import ActiveProfile
from model_fit.assessment.types.user_choice import RetainedProfileChoice
from model_fit.assessment.types.decision import AssessmentDecision, DecisionKind


def validated_active_profile(request: object) -> ActiveProfile:
    if not isinstance(request, dict):
        raise ValueError("Preflight input is not an object")
    active = request.get("active_profile")
    if not isinstance(active, dict) or not all(
        (field in active for field in ("model", "effort", "speed"))
    ):
        raise ValueError("Active profile fields are incomplete")
    if not isinstance(active["model"], str) or not isinstance(active["effort"], str):
        raise ValueError("Active model and effort must come from session state")
    if active["speed"] is not None and (not isinstance(active["speed"], str)):
        raise ValueError("Active speed must be a string or null")
    return {
        "model": active["model"],
        "effort": active["effort"],
        "speed": active["speed"],
    }


def validated_request(
    request: object,
) -> tuple[str, ActiveProfile, str | None, RetainedProfileChoice | None]:
    active = validated_active_profile(request)
    if not isinstance(request, dict):
        raise ValueError("Preflight input is not an object")
    native_input = request.get("input")
    if "input" in request and (
        not isinstance(native_input, list)
        or not native_input
        or (not all((isinstance(item, dict) for item in native_input)))
    ):
        raise ValueError("Native input must be a nonempty array of objects")
    task = request.get("task")
    if task is None and native_input:
        task = "Assess the original native message, including its attachments."
    if not isinstance(task, str) or not task.strip():
        raise ValueError("Task or native input is required")
    context = request.get("context")
    if context is not None and (not isinstance(context, str) or len(context) > 20000):
        raise ValueError("Task context must be at most 20000 characters")
    prior = request.get("prior_choice")
    if prior is not None:
        if (
            not isinstance(prior, dict)
            or set(prior) != {"user_selected", "same_work", "profile"}
            or prior["user_selected"] is not True
            or (prior["same_work"] is not True)
            or (
                validated_active_profile({"active_profile": prior["profile"]}) != active
            )
        ):
            raise ValueError(
                "prior_choice does not confirm this active profile and work"
            )
    choice: RetainedProfileChoice | None = (
        {"user_selected": True, "same_work": True, "profile": active}
        if prior is not None
        else None
    )
    return (task, active, context, choice)


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
