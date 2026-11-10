from __future__ import annotations

from collections.abc import Callable

from model_fit.autoswitch.state import transitions
from model_fit.autoswitch.handoff.prepare import prepare
from model_fit.submission.types.evaluation import AssessmentRunner
from model_fit.autoswitch.types.audit import AuditWriter
from model_fit.submission.types.evaluation import AssessmentContextReader
from model_fit.autoswitch.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.native_input import codec
from model_fit.autoswitch.types.disposition import (
    AssessmentPending,
    BlockedTurn,
    PreparedTransfer,
    QueuePending,
    TurnDisposition,
)
from model_fit.autoswitch.handoff.control_message import CONTROL_PROMPTS

from model_fit.submission.types.input import SubmissionInput
from model_fit.autoswitch.recommendation.types.storage import (
    RecommendationStore,
)
from model_fit.autoswitch.state.types.storage import TransferStateStore
from model_fit.autoswitch.handoff.types.clock import Clock


def submit(
    event: SubmissionInput,
    *,
    assessor: AssessmentRunner,
    audit: AuditWriter,
    recommendations: RecommendationStore,
    clock: Clock,
    context_failure: type[Exception],
    context_reason: Callable[[Exception, str], str | None],
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
                transitions.continue_transfer(slot, state, event.turn_id)
                return QueuePending()
            if (
                state is not None
                and state["phase"] == "ready"
                and (not state.get("pending_assessment"))
            ):
                transitions.continue_transfer(slot, state, event.turn_id)
                audit(event.thread_id, event.turn_id, "auto_handoff_continued")
                return PreparedTransfer(event.thread_id, event.turn_id, state)
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
                transitions.release(slot)
            transitions.register_submission(
                slot, event, codec.prompt_digest(event.text)
            )
    if immediate:
        return prepare(
            event,
            assessor=assessor,
            audit=audit,
            recommendations=recommendations,
            clock=clock,
            context_failure=context_failure,
            context_reason=context_reason,
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
