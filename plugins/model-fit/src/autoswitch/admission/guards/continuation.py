from __future__ import annotations

from model_fit.autoswitch.state.types.record import HandoffStateRecord

from model_fit.autoswitch.admission.types.tools import TransferTools
from model_fit.autoswitch.admission.types.input import ToolAdmissionInput


def can_continue_admitted_tool(
    event: ToolAdmissionInput,
    state: HandoffStateRecord | None,
    *,
    actions: TransferTools,
) -> bool:
    if can_continue_failed_assessment(event, state, actions=actions):
        return True
    if (
        state is None
        or state.get("pending_assessment")
        or (not isinstance(event.turn_id, str))
        or actions.matches_transfer(event)
        or actions.matches_assessment(event)
    ):
        return False
    if state["phase"] == "passed":
        return state["source_turn_id"] == event.turn_id
    if state["phase"] == "queued":
        return state.get("replay_turn_id") == event.turn_id
    return False


def can_continue_failed_assessment(
    event: ToolAdmissionInput,
    state: HandoffStateRecord | None,
    *,
    actions: TransferTools,
) -> bool:
    if state is None or not event.turn_id:
        return False
    if state["phase"] not in {"submitted", "passed", "ready"}:
        return False
    pending = state.get("pending_assessment")
    if pending is None or pending.get("turn_id") != event.turn_id:
        return False
    if pending.get("status") != "failed":
        return False
    if pending.get("failure_reason") != "assessment_failed":
        return False
    if actions.matches_transfer(event) or actions.matches_assessment(event):
        return False
    return True
