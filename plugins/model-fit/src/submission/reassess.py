from __future__ import annotations

from collections.abc import Callable
from typing import Any

from model_fit.autoswitch.state import transitions
from model_fit.autoswitch.exceptions.unavailable import SubmissionUnavailable
from model_fit.submission.types.evaluation import AssessmentRunner
from model_fit.autoswitch.types.audit import AuditWriter
from model_fit.submission.types.evaluation import AssessmentContextReader
from model_fit.autoswitch.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.autoswitch.handoff.types.input_reader import NativeInputReader
from model_fit.autoswitch.types.output import HookOutputRenderer
from model_fit.submission.types.input import SubmissionInput
from model_fit.autoswitch.recommendation.types.storage import (
    RecommendationStore,
)
from model_fit.autoswitch.state.types.storage import TransferStateStore
from model_fit.autoswitch.handoff.types.clock import Clock
from model_fit.submission.assess import assess_submitted


def reassess(
    requirements: str,
    decode,
    *,
    assessor: AssessmentRunner,
    assessment_failure: tuple[type[Exception], ...],
    audit: AuditWriter,
    recommendations: RecommendationStore,
    caller_thread: str | None,
    clock: Clock,
    context_failure: type[Exception],
    context_reason: Callable[[Exception, str], str | None],
    inputs: NativeInputReader,
    conversation: NativeConversationFactory,
    presentation: HookOutputRenderer,
    read_context: AssessmentContextReader,
    store: TransferStateStore,
    working_directory: Callable[[], str],
) -> dict[str, Any]:
    if not isinstance(requirements, str) or not requirements.strip():
        raise ValueError("Changed requirements must be nonempty")
    requirements_context = (
        "New requirements discovered by the executor after reading sources (not a new user message):\n"
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
    event = SubmissionInput(
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
