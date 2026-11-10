from __future__ import annotations

from model_fit.autoswitch.lifecycle import handoff as handoff_lifecycle
from model_fit.autoswitch.types.queue import QueueConfirmation


from typing import Callable

from model_fit.autoswitch.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.autoswitch.state.types.storage import TransferStateStore
from model_fit.autoswitch.handoff.expiry import HANDOFF_TTL_SECONDS
from model_fit.autoswitch.handoff.types.clock import Clock


def enqueue(
    thread_id: str,
    turn_id: str,
    *,
    caller_thread: str | None,
    clock: Clock,
    conversation: NativeConversationFactory,
    queue_rejection: type[Exception],
    store: TransferStateStore,
    working_directory: Callable[[], str],
) -> QueueConfirmation:
    if caller_thread and caller_thread != thread_id:
        raise ValueError("Queue helper must run in the target Desktop thread")
    with store.transaction(thread_id, operation="queue", turn_id=turn_id) as slot:
        state = slot.load()
        if state is None or state["source_turn_id"] != turn_id:
            raise ValueError("No matching Model Fit handoff")
        if state["phase"] == "queued":
            return QueueConfirmation(
                state["queued_submission_id"], already_confirmed=True
            )
        if state.get("pending_assessment") is not None:
            raise RuntimeError("New native input must be assessed before queueing")
        if state["phase"] == "rejected":
            raise RuntimeError("Queue rejected this handoff; send a new prompt")
        if state["phase"] != "ready":
            raise RuntimeError(
                "Previous queue attempt has an unknown outcome; do not retry"
            )
        if (
            clock() - state.get("transfer_authorized_at", state["created_at"])
            > HANDOFF_TTL_SECONDS
        ):
            raise ValueError("Model Fit handoff expired")
        with conversation(working_directory()) as app:
            selected_profile = app.profile(thread_id)
            if selected_profile != (state["target_model"], state["target_effort"]):
                raise ValueError("Target profile was not applied to the next turn")
            content = app.handoff_input(thread_id, state)
            handoff_lifecycle.begin_queue(slot, state, turn_id, content)
            try:
                submission = app.enqueue(thread_id, turn_id, content)
            except queue_rejection:
                handoff_lifecycle.reject(slot, state)
                raise
            handoff_lifecycle.receipt(slot, state, submission)
        handoff_lifecycle.confirm_queue(slot, state, clock())
        return QueueConfirmation(state["queued_submission_id"])
