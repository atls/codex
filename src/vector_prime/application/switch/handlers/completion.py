from __future__ import annotations

from vector_prime.application.assessment.types.state import Failed
from vector_prime.application.switch.helpers.transfer import is_control_turn
from vector_prime.application.handoff.types.state import QueuedTransfer

from vector_prime.application.switch import lifecycle as switch_lifecycle


from contextlib import AbstractContextManager
from typing import Callable

from vector_prime.application.switch.types.audit import AuditWriter
from vector_prime.application.answer.limits import MAX_REPLAY_EVAL_CHARS
from vector_prime.application.answer.types.input import ReplayAnswerInput
from vector_prime.application.handoff.types.conversation import NativeConversation
from vector_prime.application.submission.helpers import content as codec
from vector_prime.application.switch.types.disposition import (
    BlockedTurn,
    TurnDisposition,
    UnrelatedAnswer,
)

from vector_prime.application.switch.types.storage import TransferStateStore


def finish(
    event: ReplayAnswerInput,
    *,
    audit: AuditWriter,
    conversation: Callable[[str | None], AbstractContextManager[NativeConversation]],
    relevance: Callable[[str, str, str], str],
    store: TransferStateStore,
) -> TurnDisposition | None:
    if not isinstance(event.thread_id, str) or event.stop_hook_active is True:
        return None
    thread_id = event.thread_id
    turn_id = event.turn_id
    answer = event.answer
    if (
        not isinstance(turn_id, str)
        or not isinstance(answer, str)
        or (not answer.strip())
    ):
        return None
    with store.transaction(thread_id, operation="stop", turn_id=turn_id) as slot:
        state = slot.load()
        pending = state.get("pending_assessment") if state is not None else None
        if pending is not None:
            if pending.turn_id != turn_id or isinstance(pending.progress, Failed):
                return None
            return BlockedTurn(
                "Model Fit: before answering, run the technical assessment command from this turn's instructions."
            )
        if (
            state is not None
            and state["phase"] in {"ready", "rejected"}
            and (
                state["source_turn_id"] == turn_id
                or (state["phase"] == "ready" and is_control_turn(state, turn_id))
            )
        ):
            phase = state["phase"]
            switch_lifecycle.admit(slot, turn_id, recover_rejected=True)
            audit(
                thread_id,
                turn_id,
                "auto_handoff_not_queued",
                {
                    "hook_event": "Stop",
                    "reason_code": (
                        "queue_rejected"
                        if phase == "rejected"
                        else "technical_turn_finished_before_queue"
                    ),
                    "state_phase": phase,
                },
            )
            if state["source_turn_id"] != turn_id:
                return None
            return BlockedTurn(
                "Model Fit: the original request was not queued. The technical handoff instructions no longer apply. "
                "Continue this turn on the active profile and respond to the original user input with its attachments. "
                "Do not retry the handoff or ask the user to resend the input."
            )
    if state is None:
        return None
    assessed = (
        state["phase"] == "passed"
        and state["source_turn_id"] == turn_id
        and (state.get("assessment_decision") == "keep")
    )
    transfer = state.get("transfer")
    queued = (
        transfer
        if isinstance(transfer, QueuedTransfer) and transfer.replay_turn_id == turn_id
        else None
    )
    if not assessed and queued is None:
        return None
    with conversation(event.working_directory) as app:
        if assessed:
            content = app.accepted_input(thread_id, turn_id).content
            verified_input = content
        else:
            assert queued is not None
            content = app.handoff_input(thread_id, queued.source)
            replay = app.replay_input(thread_id, turn_id)
            if replay is None:
                audit(thread_id, turn_id, "auto_stop_steered_or_unverified")
                return None
            verified_input = replay
            evidence = queued.input_evidence
            if (
                evidence is None
                or evidence.kind != "native_input"
                or codec.input_digest(replay) != evidence.digest
            ):
                audit(thread_id, turn_id, "auto_stop_input_unverified")
                return None
    if any((item.get("type") != "text" for item in content)):
        audit(thread_id, turn_id, "auto_stop_multimodal_unchecked")
        return None
    request = codec.input_text(content).strip()
    if (
        not request
        or len(request) > MAX_REPLAY_EVAL_CHARS
        or len(answer) > MAX_REPLAY_EVAL_CHARS
    ):
        audit(thread_id, turn_id, "auto_stop_size_unchecked")
        return None
    verdict = relevance(
        request, (queued.task_inference or "") if queued is not None else "", answer
    )
    audit(thread_id, turn_id, f"auto_stop_{verdict}")
    if verdict != "unrelated":
        return None
    with store.transaction(thread_id, operation="stop", turn_id=turn_id) as slot:
        current = slot.load()
    if current != state:
        return None
    with conversation(event.working_directory) as app:
        latest_input = (
            app.accepted_input(thread_id, turn_id).content
            if assessed
            else app.replay_input(thread_id, turn_id)
        )
    if latest_input is None or codec.input_digest(latest_input) != codec.input_digest(
        verified_input
    ):
        audit(thread_id, turn_id, "auto_stop_input_changed")
        return None
    with store.transaction(thread_id, operation="stop", turn_id=turn_id) as slot:
        current = slot.load()
    if current != state:
        return None
    return UnrelatedAnswer()
