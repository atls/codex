from vector_prime.application.assessment.constraints.is_context_within_limit import (
    is_context_within_limit,
)
from vector_prime.application.assessment.helpers.context import requirements_context
from vector_prime.application.assessment.decoding import (
    decode_profile,
    decode_retained_choice,
)
from vector_prime.application.assessment.constraints.is_retained_choice_consistent import (
    is_retained_choice_consistent,
)
from vector_prime.application.assessment.types.profile import ActiveProfile
from vector_prime.application.assessment.types.user_choice import RetainedProfileChoice


def validated_active_profile(request: object) -> ActiveProfile:
    if not isinstance(request, dict):
        raise ValueError("Preflight input is not an object")
    return decode_profile(request.get("active_profile"))


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
    if not is_context_within_limit(context):
        raise ValueError("Task context must be at most 20000 characters")
    prior = request.get("prior_choice")
    choice = decode_retained_choice(prior) if prior is not None else None
    if choice is not None and not is_retained_choice_consistent(choice, active):
        raise ValueError("prior_choice does not confirm this active profile and work")
    return (task, active, context, choice)


def require_reassessment(requirements: str) -> None:
    if not isinstance(requirements, str) or not requirements.strip():
        raise ValueError("Changed requirements must be nonempty")
    if not is_context_within_limit(requirements_context(requirements)):
        raise ValueError("Changed requirements exceed the assessment context limit")
