from __future__ import annotations

from vector_prime.application.handoff.helpers.instruction import transfer_instruction
from vector_prime.application.handoff import lifecycle as handoff_lifecycle
from vector_prime.application.switch import lifecycle as switch_lifecycle


from vector_prime.application.switch.handlers.processing import evaluate
from vector_prime.application.assessment.types.execution import AssessmentRunner
from vector_prime.application.switch.types.audit import AuditWriter
from vector_prime.application.assessment.types.execution import AssessmentContextReader
from vector_prime.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from vector_prime.application.submission.helpers import content as codec
from vector_prime.application.switch.types.disposition import (
    AssessmentPending,
    BlockedTurn,
    PreparedTransfer,
    QueuePending,
    TurnDisposition,
)
from vector_prime.application.handoff.control_message import CONTROL_PROMPTS

from vector_prime.application.submission.types.input import SubmissionInput
from vector_prime.application.assessment.types.cache import (
    ResultCache,
)
from vector_prime.application.switch.types.storage import TransferStateStore
from vector_prime.application.handoff.types.clock import Clock


def accept(
    event: SubmissionInput,
    *,
    assessor: AssessmentRunner,
    audit: AuditWriter,
    recommendations: ResultCache,
    clock: Clock,
    conversation: NativeConversationFactory,
    read_context: AssessmentContextReader,
    store: TransferStateStore,
) -> TurnDisposition | None:
    audit(
        event.thread_id,
        event.turn_id,
        "auto_started",
        {
            "hook_event": "UserPromptSubmit",
            "root_session_id": event.session_id or event.thread_id,
            "agent_id": event.thread_id
            if event.session_id and event.session_id != event.thread_id
            else None,
        },
    )
    with store.transaction(
        event.thread_id, operation="prompt_submit", turn_id=event.turn_id
    ) as slot:
        state = slot.load()
        if slot.unsafe():
            raise ValueError("Unsafe Model Fit state")
        if event.text.strip() in CONTROL_PROMPTS:
            if state is not None and state["phase"] == "queued":
                handoff_lifecycle.continue_transfer(slot, state, event.turn_id)
                return QueuePending()
            if (
                state is not None
                and state["phase"] == "ready"
                and (not state.get("pending_assessment"))
            ):
                handoff_lifecycle.continue_transfer(slot, state, event.turn_id)
                audit(event.thread_id, event.turn_id, "auto_handoff_continued")
                return PreparedTransfer(
                    event.thread_id, event.turn_id, transfer_instruction(state)
                )
            return BlockedTurn(
                "Model Fit: the service handoff is not prepared, or new input is still awaiting assessment."
            )
        immediate = state is not None and (
            state["phase"] == "attempting"
            or (
                state["phase"] == "rejected"
                and state["source_turn_id"] == event.turn_id
            )
        )
        if not immediate:
            if state is not None and state["phase"] == "rejected":
                handoff_lifecycle.release(slot)
            switch_lifecycle.register_submission(
                slot, event, codec.prompt_digest(event.text)
            )
    if immediate:
        return evaluate(
            event,
            assessor=assessor,
            audit=audit,
            recommendations=recommendations,
            clock=clock,
            conversation=conversation,
            read_context=read_context,
            store=store,
        )
    audit(
        event.thread_id,
        event.turn_id,
        "auto_deferred",
        {"hook_event": "UserPromptSubmit"},
    )
    return AssessmentPending()
