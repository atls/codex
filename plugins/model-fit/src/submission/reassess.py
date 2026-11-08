from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from model_fit.autoswitch import transitions
from model_fit.autoswitch.failures.unavailable import SubmissionUnavailable
from model_fit.autoswitch.ports.conversation import Conversation
from model_fit.autoswitch.ports.inputs import Inputs
from model_fit.autoswitch.ports.presentation import Presentation
from model_fit.autoswitch.ports.recommendations import Recommendations
from model_fit.autoswitch.ports.store import Store
from model_fit.autoswitch.requests.prompt import Prompt
from model_fit.submission.assess import assess_submitted


def reassess(
    requirements: str,
    decode,
    *,
    assessor: Callable[[dict[str, Any]], dict[str, Any]],
    assessment_failure: tuple[type[Exception], ...],
    audit: Callable[..., Any],
    recommendations: Recommendations,
    caller_thread: str | None,
    clock: Callable[[], float],
    context_failure: type[Exception],
    context_reason: Callable[[Exception, str], str | None],
    inputs: Inputs,
    conversation: Callable[[object], AbstractContextManager[Conversation]],
    presentation: Presentation,
    read_context: Callable[[Prompt], dict[str, Any]],
    store: Store,
    working_directory: Callable[[], str],
) -> dict[str, Any]:
    if not isinstance(requirements, str) or not requirements.strip():
        raise ValueError("Changed requirements must be nonempty")
    requirements_context = (
        "Новые требования, обнаруженные исполнителем после чтения источников (не новое сообщение пользователя):\n"
        + requirements
        + "\n\n"
    )
    if len(requirements_context) > 20000:
        raise ValueError("Changed requirements exceed the assessment context limit")
    thread_id = caller_thread
    if not thread_id:
        raise SubmissionUnavailable(None, "native_thread_required")
    snapshot = store.snapshot(thread_id)
    if (
        snapshot is None
        or snapshot.get("pending_assessment")
        or snapshot["phase"] not in {"passed", "queued"}
    ):
        raise SubmissionUnavailable(thread_id, "reassessment_not_admitted")
    turn_id = (
        snapshot.get("replay_turn_id")
        if snapshot["phase"] == "queued"
        else snapshot["source_turn_id"]
    )
    if not turn_id:
        raise SubmissionUnavailable(thread_id, "reassessment_not_admitted")
    cwd = working_directory()
    with conversation(cwd) as app:
        if app.latest_turn_id(thread_id) != turn_id:
            raise SubmissionUnavailable(thread_id, "reassessment_turn_changed")
        if snapshot["phase"] == "queued" and snapshot[
            "queued_submission_id"
        ] in app.queued_ids(thread_id):
            raise SubmissionUnavailable(thread_id, "reassessment_queue_pending")
        accepted = app.accepted_input(thread_id, turn_id)
        model, effort = app.profile(thread_id)
        parent_id = app.parent_thread_id(thread_id)
    source = inputs.hook_prompt(accepted.source_content)
    event = Prompt(
        thread_id,
        turn_id,
        source,
        cwd,
        model,
        {
            "session_id": parent_id or thread_id,
            "agent_id": thread_id if parent_id else None,
            "turn_id": turn_id,
            "cwd": cwd,
            "model": model,
            "prompt": source,
        },
        parent_id or thread_id,
    )
    request = read_context(event)
    request = {
        **request,
        "active_profile": {
            "model": model,
            "effort": effort,
            "speed": request["active_profile"].get("speed"),
        },
        "context": requirements_context
        + (request.get("context") or "")[: 20000 - len(requirements_context)],
    }
    with store.transaction(
        thread_id, operation="reassessment", turn_id=turn_id
    ) as slot:
        if slot.load() != snapshot:
            raise SubmissionUnavailable(thread_id, "reassessment_turn_changed")
        transitions.register_submission(slot, event, inputs.prompt_digest(source))
        if snapshot["phase"] == "queued":
            transitions.consume_submission(
                slot, turn_id, slot.load()["pending_assessment"]
            )
            if (model, effort) != (snapshot["target_model"], snapshot["target_effort"]):
                transitions.admit(
                    slot,
                    turn_id,
                    "native_override",
                    turn_id,
                    native_profile=request["active_profile"],
                )
    return assess_submitted(
        decode,
        assessor=assessor,
        assessment_failure=assessment_failure,
        audit=audit,
        recommendations=recommendations,
        caller_thread=caller_thread,
        clock=clock,
        context_failure=context_failure,
        context_reason=context_reason,
        inputs=inputs,
        conversation=conversation,
        presentation=presentation,
        read_context=lambda _: request,
        store=store,
    )
