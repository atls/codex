from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from model_fit.autoswitch import transitions
from model_fit.autoswitch.ports.conversation import Conversation
from model_fit.autoswitch.ports.inputs import Inputs
from model_fit.autoswitch.ports.presentation import Presentation
from model_fit.autoswitch.ports.recommendations import Recommendations
from model_fit.autoswitch.ports.store import Store
from model_fit.autoswitch.prepare import prepare
from model_fit.autoswitch.requests.prompt import Prompt


def submit(
    event: Prompt,
    *,
    assessor: Callable[[dict[str, Any]], dict[str, Any]],
    audit: Callable[..., Any],
    recommendations: Recommendations,
    clock: Callable[[], float],
    context_failure: type[Exception],
    context_reason: Callable[[Exception, str], str | None],
    inputs: Inputs,
    conversation: Callable[[object], AbstractContextManager[Conversation]],
    presentation: Presentation,
    read_context: Callable[[Prompt], dict[str, Any]],
    store: Store,
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
        if event.text.strip() == presentation.control_prompt:
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
                "Model Fit: служебный перенос не подготовлен либо новый ввод ещё ожидает оценки."
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
