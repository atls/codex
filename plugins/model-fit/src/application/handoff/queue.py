"""Opt-in Desktop Model Fit handoff to a queued turn on the selected profile."""

from __future__ import annotations

from model_fit.application.handoff.configuration import HANDOFF_TTL_SECONDS
from model_fit.application.handoff.dependencies import Dependencies

from .lifecycle import Lifecycle


def enqueue(
    thread_id: str, turn_id: str, *, dependencies: Dependencies
) -> dict[str, str]:
    caller_thread = dependencies.caller_thread
    if caller_thread and caller_thread != thread_id:
        raise ValueError("Queue helper must run in the target Desktop thread")
    with dependencies.state.transaction(
        thread_id, operation="queue", turn_id=turn_id
    ) as slot:
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
            dependencies.clock()
            - state.get("transfer_authorized_at", state["created_at"])
            > HANDOFF_TTL_SECONDS
        ):
            raise ValueError("Model Fit handoff expired")
        with dependencies.native(dependencies.working_directory()) as app:
            selected_profile = app.profile(thread_id)
            if selected_profile != (state["target_model"], state["target_effort"]):
                raise ValueError("Target profile was not applied to the next turn")
            content = app.handoff_input(thread_id, state)
            queued_input = content
            state["queued_client_message_id"] = turn_id
            state.pop("prompt")
            state["source_input_digest"] = dependencies.input.input_digest(content)
            state["queued_input_digest"] = dependencies.input.input_digest(queued_input)
            state["queued_prompt_digest"] = dependencies.input.prompt_digest(
                dependencies.input.input_text(queued_input)
            )
            state["queued_hook_prompt_digest"] = dependencies.input.prompt_digest(
                dependencies.input.hook_prompt(queued_input)
            )
            Lifecycle.begin_queue(slot, state)
            try:
                submission = app.enqueue(thread_id, turn_id, queued_input)
            except dependencies.queue_rejection:
                Lifecycle.reject(slot, state)
                raise
            Lifecycle.receipt(slot, state, submission.submission_id)
            if (
                not isinstance(submission.accepted_input, list)
                or not submission.accepted_input
                or not all(isinstance(item, dict) for item in submission.accepted_input)
            ):
                raise ValueError("Native queue receipt input is unavailable")
            state["queued_input_digest"] = dependencies.input.input_digest(
                submission.accepted_input
            )
        Lifecycle.confirm_queue(slot, state, dependencies.clock())
        return {
            "queued_submission_id": state["queued_submission_id"],
            "status": "queued",
        }
