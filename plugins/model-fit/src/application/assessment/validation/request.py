from typing import Any

from model_fit.application.assessment.validation.profile import validated_active_profile


def validated_request(
    request: Any,
) -> tuple[str, dict[str, Any], str | None, dict[str, Any] | None]:
    active = validated_active_profile(request)
    native_input = request.get("input")
    if "input" in request and (
        not isinstance(native_input, list)
        or not native_input
        or not all(isinstance(item, dict) for item in native_input)
    ):
        raise ValueError("Native input must be a nonempty array of objects")
    task = request.get("task")
    if task is None and native_input:
        task = "Оцени исходное нативное сообщение, включая вложения."
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
            or prior["same_work"] is not True
            or validated_active_profile({"active_profile": prior["profile"]}) != active
        ):
            raise ValueError(
                "prior_choice does not confirm this active profile and work"
            )
    return task, active, context, prior
