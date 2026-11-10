from __future__ import annotations

from model_fit.application.assessment.types.profile import ActiveProfile
from model_fit.application.switch.state.types.record import HandoffStateRecord
from uuid import uuid4
from typing import overload

from model_fit.application.switch.exceptions.superseded import AssessmentSuperseded
from model_fit.application.switch.state.types.record import PendingAssessmentRecord
from model_fit.application.submission.types.input import SubmissionInput
from model_fit.application.switch.state.types.storage import TransferStateSlot

from model_fit.application.switch.state.commit import save_snapshot
from model_fit.application.switch.lifecycle.profile_choice import admit


@overload
def require_submission(
    slot: TransferStateSlot, expected: PendingAssessmentRecord
) -> HandoffStateRecord: ...


@overload
def require_submission(slot: TransferStateSlot, expected: None) -> None: ...


def require_submission(
    slot: TransferStateSlot, expected: PendingAssessmentRecord | None
) -> HandoffStateRecord | None:
    if expected is None:
        return None
    current = slot.load()
    if current is None or current.get("pending_assessment") != expected:
        raise AssessmentSuperseded(
            expected["thread_id"], expected["turn_id"], expected.get("generation")
        )
    return current


def register_submission(
    slot: TransferStateSlot, event: SubmissionInput, prompt_hash: str
) -> PendingAssessmentRecord:
    current = slot.load()
    if slot.unsafe() or (
        current is not None and current["phase"] in {"attempting", "rejected"}
    ):
        raise RuntimeError("Cannot replace an unresolved transfer with a submission")
    state: HandoffStateRecord = current or {
        "phase": "submitted",
        "source_turn_id": event.turn_id,
    }
    if state["phase"] == "submitted":
        state["source_turn_id"] = event.turn_id
    generation = uuid4().hex
    pending: PendingAssessmentRecord = {
        "thread_id": event.thread_id,
        "turn_id": event.turn_id,
        "root_session_id": event.session_id or event.thread_id,
        "agent_id": event.thread_id
        if event.session_id and event.session_id != event.thread_id
        else None,
        "working_directory": event.working_directory,
        "active_model": event.active_model,
        "prompt_hash": prompt_hash,
        "empty_text": not event.text.strip(),
        "status": "waiting",
        "generation": generation,
    }
    state["pending_assessment"] = pending
    save_snapshot(slot, state)
    return pending


def start_assessment(slot: TransferStateSlot) -> PendingAssessmentRecord:
    state = slot.load()
    pending = state.get("pending_assessment") if state is not None else None
    if state is None or not pending:
        raise ValueError("No submitted Model Fit input")
    if pending["status"] != "waiting":
        raise RuntimeError("Submitted Model Fit input is not awaiting assessment")
    pending["status"] = "running"
    save_snapshot(slot, state)
    return pending


def fail_assessment(
    slot: TransferStateSlot, pending: PendingAssessmentRecord, reason: str | None = None
) -> None:
    state = slot.load()
    stored = state.get("pending_assessment") if state is not None else None
    if state is not None and stored is not None and stored == pending:
        stored["status"] = "failed"
        if reason is not None:
            stored["failure_reason"] = reason
        save_snapshot(slot, state)


def abstain_assessment(
    slot: TransferStateSlot, pending: PendingAssessmentRecord
) -> bool:
    state = slot.load()
    if (
        state is None
        or not pending.get("generation")
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
            and pending.get("generation") is not None
            and (state.get("assessment_generation") == pending["generation"])
        )
    ):
        state.pop("pending_assessment", None)
        if state["phase"] == "passed" and assessed_profile is not None:
            state["assessed_profile"] = assessed_profile
        save_snapshot(slot, state)


def consume_submission(
    slot: TransferStateSlot, turn_id: str, pending: PendingAssessmentRecord
) -> None:
    current = slot.load()
    if (
        current is None
        or current["phase"] != "queued"
        or current.get("pending_assessment") != pending
    ):
        raise RuntimeError("Native queue receipt changed during assessment")
    save_snapshot(
        slot,
        {
            "phase": "submitted",
            "source_turn_id": turn_id,
            "pending_assessment": pending,
        },
    )
