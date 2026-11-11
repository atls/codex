from __future__ import annotations

from typing import overload
from vector_prime.application.switch.guards.progress import (
    require_registration_state,
    require_admission_state,
    require_consumption,
)
from vector_prime.application.assessment.guards.generation import generation_known
from vector_prime.application.assessment.guards.generation import require_current
from vector_prime.application.assessment import lifecycle as assessment_lifecycle
from vector_prime.application.assessment.types.state import PendingAssessmentRecord
from vector_prime.application.submission.types.input import SubmissionInput
from vector_prime.application.assessment.types.profile import ActiveProfile
from vector_prime.application.switch.types.state import ProcessSnapshot
from vector_prime.application.switch.types.storage import TransferStateSlot


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
    require_admission_state(current)
    state: ProcessSnapshot = {"phase": "passed", "source_turn_id": turn_id}
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
        state["assessment_generation"] = assessment_lifecycle.new_generation()
        slot.save(state)
    else:
        slot.save_transition(state)


@overload
def require_submission(
    slot: TransferStateSlot, expected: PendingAssessmentRecord
) -> ProcessSnapshot: ...


@overload
def require_submission(slot: TransferStateSlot, expected: None) -> None: ...


def require_submission(
    slot: TransferStateSlot, expected: PendingAssessmentRecord | None
) -> ProcessSnapshot | None:
    if expected is None:
        return None
    current = slot.load()
    require_current(
        expected, current.get("pending_assessment") if current is not None else None
    )
    assert current is not None
    return current


def register_submission(
    slot: TransferStateSlot,
    event: SubmissionInput,
    prompt_hash: str,
    *,
    assessment: PendingAssessmentRecord | None = None,
) -> PendingAssessmentRecord:
    current = slot.load()
    require_registration_state(current, unsafe=slot.unsafe())
    state: ProcessSnapshot = current or {
        "phase": "submitted",
        "source_turn_id": event.turn_id,
    }
    if state["phase"] == "submitted":
        state["source_turn_id"] = event.turn_id
    pending = (
        assessment
        if assessment is not None
        else assessment_lifecycle.register(event, prompt_hash)
    )
    state["pending_assessment"] = pending
    slot.save_transition(state)
    return pending


def start_assessment(slot: TransferStateSlot) -> PendingAssessmentRecord:
    state = slot.load()
    pending = state.get("pending_assessment") if state is not None else None
    if state is None or not pending:
        raise ValueError("No submitted Model Fit input")
    assessment_lifecycle.start(pending)
    slot.save_transition(state)
    return pending


def fail_assessment(
    slot: TransferStateSlot, pending: PendingAssessmentRecord, reason: str | None = None
) -> None:
    state = slot.load()
    stored = state.get("pending_assessment") if state is not None else None
    if state is not None and stored is not None and stored == pending:
        assessment_lifecycle.fail(stored, reason)
        slot.save_transition(state)


def abstain_assessment(
    slot: TransferStateSlot, pending: PendingAssessmentRecord
) -> bool:
    state = slot.load()
    if (
        state is None
        or not generation_known(pending.get("generation"))
        or state.get("assessment_generation") != pending["generation"]
        or (state.get("pending_assessment") not in (None, pending))
        or (state["phase"] not in {"submitted", "passed", "ready"})
    ):
        return False
    admit(slot, pending["turn_id"], "unknown", state.get("profile_context_turn_id"))
    finish_assessment(slot, pending)
    return True


def finish_assessment(
    slot: TransferStateSlot,
    pending: PendingAssessmentRecord,
    assessed_profile: ActiveProfile | None = None,
) -> None:
    state = slot.load()
    if state is not None and (
        state.get("pending_assessment") == pending
        or (
            state.get("pending_assessment") is None
            and generation_known(pending.get("generation"))
            and (state.get("assessment_generation") == pending["generation"])
        )
    ):
        state.pop("pending_assessment", None)
        if state["phase"] == "passed" and assessed_profile is not None:
            state["assessed_profile"] = assessed_profile
        slot.save_transition(state)


def consume_submission(
    slot: TransferStateSlot, turn_id: str, pending: PendingAssessmentRecord
) -> None:
    current = slot.load()
    require_consumption(current, pending)
    slot.save_transition(
        {
            "phase": "submitted",
            "source_turn_id": turn_id,
            "pending_assessment": pending,
        },
    )
