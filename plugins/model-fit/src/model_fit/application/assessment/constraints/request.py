from model_fit.application.assessment.types.profile import ActiveProfile
from model_fit.application.assessment.types.user_choice import RetainedProfileChoice


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
