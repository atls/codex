from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Callable

from model_fit.answer.limits import MAX_REPLAY_EVAL_CHARS
from model_fit.autoswitch.state import transitions
from model_fit.answer.types.input import ReplayAnswerInput
from model_fit.autoswitch.handoff.types.conversation import NativeConversation
from model_fit.native_input import codec
from model_fit.autoswitch.types.output import HookOutputRenderer
from model_fit.autoswitch.state.types.storage import TransferStateStore


def guard_replay_answer(
    event: ReplayAnswerInput,
    *,
    audit: Callable[..., Any],
    conversation: Callable[[object], AbstractContextManager[NativeConversation]],
    presentation: HookOutputRenderer,
    relevance: Callable[[str, str, str], str],
    store: TransferStateStore,
) -> dict[str, Any] | None:
    if event.stop_hook_active is True:
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
            if pending["turn_id"] != turn_id or pending["status"] == "failed":
                return None
            return presentation.block(
                "Model Fit: before answering, run the technical assessment command from this turn's instructions."
            )
        if (
            state is not None
            and state["phase"] == "ready"
            and (turn_id in {state["source_turn_id"], state.get("control_turn_id")})
        ):
            transitions.admit(slot, turn_id)
            audit(
                thread_id,
                turn_id,
                "auto_handoff_not_queued",
                {
                    "hook_event": "Stop",
                    "reason_code": "technical_turn_finished_before_queue",
                    "state_phase": "ready",
                },
            )
            return None
    if state is None:
        return None
    assessed = (
        state["phase"] == "passed"
        and state["source_turn_id"] == turn_id
        and (state.get("assessment_decision") == "keep")
    )
    replay_bound = state["phase"] == "queued" and state.get("replay_turn_id") == turn_id
    if not assessed and (not replay_bound):
        return None
    with conversation(event.working_directory) as app:
        if assessed:
            content = app.accepted_input(thread_id, turn_id).content
            verified_input = content
        else:
            content = app.handoff_input(thread_id, state)
            replay = app.replay_input(thread_id, turn_id)
            if replay is None:
                audit(thread_id, turn_id, "auto_stop_steered_or_unverified")
                return None
            verified_input = replay
            if codec.input_digest(replay) != state["queued_input_digest"]:
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
    verdict = relevance(request, state.get("task_inference", ""), answer)
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
    return presentation.block(presentation.replay_stop_reason)
