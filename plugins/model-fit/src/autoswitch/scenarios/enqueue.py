from __future__ import annotations

from model_fit.autoswitch.lifecycle import handoff as handoff_lifecycle
from model_fit.autoswitch.types.queue import QueueConfirmation
from model_fit.autoswitch.handoff.types.queue_receipt import NativeQueueRejection


from typing import Callable

from model_fit.autoswitch.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.autoswitch.state.types.storage import TransferStateStore
from model_fit.autoswitch.handoff.types.clock import Clock


def enqueue(
    thread_id: str,
    turn_id: str,
    *,
    caller_thread: str | None,
    clock: Clock,
    conversation: NativeConversationFactory,
    store: TransferStateStore,
    working_directory: Callable[[], str],
) -> QueueConfirmation:
    handoff_lifecycle.require_queue_executor(caller_thread, thread_id)
    with store.transaction(thread_id, operation="queue", turn_id=turn_id) as slot:
        state = slot.load()
        prepared = handoff_lifecycle.queue_preparation(state, turn_id, clock())
        if isinstance(prepared, QueueConfirmation):
            return prepared
        assert state is not None
        with conversation(working_directory()) as app:
            handoff_lifecycle.require_transfer_profile(prepared, app.profile(thread_id))
            content = app.handoff_input(thread_id, state)
            handoff_lifecycle.begin_queue(slot, state, turn_id, content)
            submission = app.enqueue(thread_id, turn_id, content)
            if isinstance(submission, NativeQueueRejection):
                handoff_lifecycle.reject(slot, state)
                raise submission.error
            handoff_lifecycle.receipt(slot, state, submission)
        confirmed = handoff_lifecycle.confirm_queue(slot, state, clock())
        return QueueConfirmation(confirmed.submission_id)
