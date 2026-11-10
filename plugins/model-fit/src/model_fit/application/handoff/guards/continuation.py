from model_fit.application.switch.types.state import ProcessSnapshot
from model_fit.application.handoff.helpers.progress import prepared_handoff
from model_fit.application.handoff.types.progress import QueuedHandoff


def require_control_state(state: ProcessSnapshot) -> None:
    if state["phase"] not in {"ready", "queued"}:
        raise RuntimeError("Only a prepared transfer accepts a control turn")
    if state["phase"] == "ready":
        prepared_handoff(state)


def require_replay_turn(queued: QueuedHandoff, turn_id: str) -> None:
    if queued.replay_turn_id not in (None, turn_id):
        raise RuntimeError("Replay does not belong to this queued transfer")


def require_accepted_replay(state: ProcessSnapshot, queued_ids: set[str]) -> None:
    if state["phase"] != "queued":
        raise RuntimeError("Native queue receipt changed during assessment")
    if state["queued_submission_id"] in queued_ids:
        raise RuntimeError("Previous native submission is still queued")


def reuses_original_input(turn_id: str, state: ProcessSnapshot) -> bool:
    return turn_id in {
        state["source_turn_id"],
        *state.get("continuation_turn_ids", []),
    }
