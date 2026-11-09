from __future__ import annotations

from collections.abc import Callable
from typing import Any

from model_fit.autoswitch import transitions
from model_fit.autoswitch.handoff_preparation import prepare
from model_fit.autoswitch.interfaces.assessment_runner import AssessmentRunner
from model_fit.autoswitch.interfaces.audit import AuditWriter
from model_fit.autoswitch.interfaces.context_reader import AssessmentContextReader
from model_fit.autoswitch.interfaces.conversation_factory import (
    NativeConversationFactory,
)
from model_fit.autoswitch.interfaces.inputs import NativeInputReader
from model_fit.autoswitch.interfaces.presentation import HookOutputRenderer
from model_fit.autoswitch.interfaces.prompt import SubmissionInput
from model_fit.autoswitch.interfaces.recommendations import RecommendationStore
from model_fit.autoswitch.interfaces.store import TransferStateStore
from model_fit.autoswitch.types.clock import Clock


def submit(
    event: SubmissionInput,
    *,
    assessor: AssessmentRunner,
    audit: AuditWriter,
    recommendations: RecommendationStore,
    clock: Clock,
    context_failure: type[Exception],
    context_reason: Callable[[Exception, str], str | None],
    inputs: NativeInputReader,
    conversation: NativeConversationFactory,
    presentation: HookOutputRenderer,
    read_context: AssessmentContextReader,
    store: TransferStateStore,
) -> dict[str, Any] | None:
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
        if event.text.strip() in presentation.control_prompts:
            if state is not None and state["phase"] == "queued":
                transitions.continue_transfer(slot, state, event.turn_id)
                return presentation.queued_context()
            if (
                state is not None
                and state["phase"] == "ready"
                and (not state.get("pending_assessment"))
            ):
                transitions.continue_transfer(slot, state, event.turn_id)
                audit(event.thread_id, event.turn_id, "auto_handoff_continued")
                return presentation.control_context(
                    event.thread_id, event.turn_id, state
                )
            return presentation.block(
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
                slot, event, inputs.prompt_digest(event.text)
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
            inputs=inputs,
            conversation=conversation,
            presentation=presentation,
            read_context=read_context,
            store=store,
        )
    audit(
        event.thread_id,
        event.turn_id,
        "auto_deferred",
        {"hook_event": "UserPromptSubmit"},
    )
    return presentation.pending_context()
