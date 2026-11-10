from __future__ import annotations

from model_fit.application.assessment.types.profile import ActiveProfile
from model_fit.application.switch.state.types.record import HandoffStateRecord
from uuid import uuid4

from model_fit.application.switch.state.types.storage import TransferStateSlot

from model_fit.application.switch.state.commit import save_snapshot


def admit(
    slot: TransferStateSlot,
    turn_id: str,
    decision: str | None = None,
    profile_context_turn_id: str | None = None,
    native_profile: ActiveProfile | None = None,
    *,
    supersede_assessment: bool = False,
) -> None:
    current = slot.load()
    if current is not None and current["phase"] not in {"ready", "passed", "submitted"}:
        raise RuntimeError("Admission cannot discard an unresolved queue attempt")
    state: HandoffStateRecord = {"phase": "passed", "source_turn_id": turn_id}
    if current is not None and current.get("assessed_profile") is not None:
        state["assessed_profile"] = current["assessed_profile"]
    if (
        current is not None
        and (current.get("pending_assessment") or {}).get("turn_id") == turn_id
    ):
        state["pending_assessment"] = current["pending_assessment"]
    if decision is not None:
        state["assessment_decision"] = decision
    if profile_context_turn_id is not None:
        state["profile_context_turn_id"] = profile_context_turn_id
        if native_profile is not None:
            state["native_profile"] = native_profile
        elif (
            current is not None
            and current.get("profile_context_turn_id") == profile_context_turn_id
            and (current.get("native_profile") is not None)
        ):
            state["native_profile"] = current["native_profile"]
    if supersede_assessment:
        state["assessment_generation"] = uuid4().hex
        slot.save(state)
    else:
        save_snapshot(slot, state)
