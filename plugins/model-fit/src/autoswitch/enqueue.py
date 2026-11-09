from __future__ import annotations

from typing import Callable

from model_fit.autoswitch import transitions
from model_fit.autoswitch.interfaces.conversation_factory import (
    NativeConversationFactory,
)
from model_fit.autoswitch.interfaces.inputs import NativeInputReader
from model_fit.autoswitch.interfaces.store import TransferStateStore
from model_fit.autoswitch.queue_expiry import HANDOFF_TTL_SECONDS
from model_fit.autoswitch.types.clock import Clock


def enqueue(
    thread_id: str,
    turn_id: str,
    *,
    caller_thread: str | None,
    clock: Clock,
    inputs: NativeInputReader,
    conversation: NativeConversationFactory,
    queue_rejection: type[Exception],
    store: TransferStateStore,
    working_directory: Callable[[], str],
) -> dict[str, str]:
    caller_thread = caller_thread
    if caller_thread and caller_thread != thread_id:
        raise ValueError("Queue helper must run in the target Desktop thread")
    with store.transaction(thread_id, operation="queue", turn_id=turn_id) as slot:
        state = slot.load()
        if state is None or state["source_turn_id"] != turn_id:
            raise ValueError("No matching Model Fit handoff")
        if state["phase"] == "queued":
            return {
                "queued_submission_id": state["queued_submission_id"],
                "status": "already_queued",
            }
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
            queued_input = content
            state["queued_client_message_id"] = turn_id
            state.pop("prompt")
            state["source_input_digest"] = inputs.input_digest(content)
            state["queued_input_digest"] = inputs.input_digest(queued_input)
            state["queued_prompt_digest"] = inputs.prompt_digest(
                inputs.input_text(queued_input)
            )
            state["queued_hook_prompt_digest"] = inputs.prompt_digest(
                inputs.hook_prompt(queued_input)
            )
            transitions.begin_queue(slot, state)
            try:
                submission = app.enqueue(thread_id, turn_id, queued_input)
            except queue_rejection:
                transitions.reject(slot, state)
                raise
            transitions.receipt(slot, state, submission.submission_id)
            if (
                not isinstance(submission.accepted_input, list)
                or not submission.accepted_input
                or (
                    not all(
                        (isinstance(item, dict) for item in submission.accepted_input)
                    )
                )
            ):
                raise ValueError("Native queue receipt input is unavailable")
            state["queued_input_digest"] = inputs.input_digest(
                submission.accepted_input
            )
        transitions.confirm_queue(slot, state, clock())
        return {
            "queued_submission_id": state["queued_submission_id"],
            "status": "queued",
        }
