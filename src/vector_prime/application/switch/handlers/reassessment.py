from __future__ import annotations
from vector_prime.application.assessment import lifecycle as assessment_lifecycle
from vector_prime.application.assessment.request import require_reassessment

from vector_prime.application.switch import lifecycle as switch_lifecycle


from collections.abc import Callable

from vector_prime.application.assessment.types.state import PendingAssessment
from vector_prime.application.switch.exceptions.unavailable import SubmissionUnavailable
from vector_prime.application.assessment.types.execution import AssessmentRunner
from vector_prime.application.switch.types.audit import AuditWriter
from vector_prime.application.assessment.types.execution import AssessmentContextReader
from vector_prime.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from vector_prime.application.submission.helpers import content as codec
from vector_prime.application.switch.types.disposition import (
    TurnDisposition,
)

from vector_prime.application.submission.types.input import SubmissionInput
from vector_prime.application.assessment.types.cache import (
    ResultCache,
)
from vector_prime.application.switch.types.storage import TransferStateStore
from vector_prime.application.handoff.types.clock import Clock
from vector_prime.application.switch.handlers.assessment import assess


def reassess(
    requirements: str,
    decode: Callable[[PendingAssessment, str], SubmissionInput],
    *,
    assessor: AssessmentRunner,
    audit: AuditWriter,
    recommendations: ResultCache,
    caller_thread: str | None,
    clock: Clock,
    conversation: NativeConversationFactory,
    read_context: AssessmentContextReader,
    store: TransferStateStore,
    working_directory: Callable[[], str],
) -> TurnDisposition:
    require_reassessment(requirements)
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
    if not isinstance(model, str) or not isinstance(effort, str):
        raise ValueError("Native profile unavailable for reassessment")
    source = codec.hook_prompt(accepted.source_content)
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
    with store.transaction(
        thread_id, operation="reassessment", turn_id=turn_id
    ) as slot:
        if slot.load() != snapshot:
            raise SubmissionUnavailable(thread_id, "reassessment_turn_changed")
        refreshed = assessment_lifecycle.reassess(
            event,
            request,
            requirements,
            {
                "model": model,
                "effort": effort,
                "speed": request["active_profile"].get("speed"),
            },
        )
        request = refreshed.request
        pending = switch_lifecycle.register_submission(
            slot, event, codec.prompt_digest(source), assessment=refreshed.submission
        )
        if snapshot["phase"] == "queued":
            switch_lifecycle.consume_submission(slot, turn_id, pending)
            if (model, effort) != (snapshot["target_model"], snapshot["target_effort"]):
                switch_lifecycle.admit(
                    slot,
                    turn_id,
                    "native_override",
                    turn_id,
                    native_profile=request["active_profile"],
                )
    return assess(
        decode,
        assessor=assessor,
        audit=audit,
        recommendations=recommendations,
        caller_thread=caller_thread,
        clock=clock,
        conversation=conversation,
        read_context=lambda _: request,
        store=store,
    )
