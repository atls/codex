from __future__ import annotations

from model_fit.assessment.types.profile import ActiveProfile
from model_fit.assessment.decoding import required_text
from model_fit.autoswitch.state.types.preparation import TransferPreparation
from model_fit.autoswitch.state.types.record import HandoffStateRecord
from uuid import uuid4
from typing import overload

from model_fit.autoswitch.exceptions.superseded import AssessmentSuperseded
from model_fit.autoswitch.state.types.record import PendingAssessmentRecord
from model_fit.submission.types.input import SubmissionInput
from model_fit.autoswitch.state.types.storage import TransferStateSlot


def preparation_is_current(
    current: HandoffStateRecord | None, expected: HandoffStateRecord
) -> bool:
    if current is None or current["phase"] != "ready":
        return False
    return all(
        (
            current.get("assessment_generation")
            == expected.get("assessment_generation"),
            current["source_turn_id"] == expected["source_turn_id"],
            current.get("target_model") == expected.get("target_model"),
            current.get("target_effort") == expected.get("target_effort"),
            current.get("prompt_digest") == expected.get("prompt_digest"),
        )
    )


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


def _save(slot: TransferStateSlot, state: HandoffStateRecord) -> HandoffStateRecord:
    current = slot.load()
    pending = state.get("pending_assessment")
    generation = pending.get("generation") if pending is not None else None
    if generation is None and current is not None:
        current_pending = current.get("pending_assessment")
        generation = (
            current_pending.get("generation", current.get("assessment_generation"))
            if current_pending is not None
            else current.get("assessment_generation")
        )
    if generation is not None:
        state = {**state, "assessment_generation": generation}
    slot.save(state)
    return state


def authorize_transfer(
    slot: TransferStateSlot, state: HandoffStateRecord, now: float
) -> None:
    _save(slot, {**state, "transfer_authorized_at": now})


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
    _save(slot, state)
    return pending


def start_assessment(slot: TransferStateSlot) -> PendingAssessmentRecord:
    state = slot.load()
    pending = state.get("pending_assessment") if state is not None else None
    if state is None or not pending:
        raise ValueError("No submitted Model Fit input")
    if pending["status"] != "waiting":
        raise RuntimeError("Submitted Model Fit input is not awaiting assessment")
    pending["status"] = "running"
    _save(slot, state)
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
        _save(slot, state)


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
        _save(slot, state)


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
    _save(
        slot,
        {
            "phase": "submitted",
            "source_turn_id": turn_id,
            "pending_assessment": pending,
        },
    )


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
        _save(slot, state)


def stage(
    slot: TransferStateSlot, preparation: TransferPreparation
) -> HandoffStateRecord:
    current = slot.load()
    if current is not None and current["phase"] not in {"passed", "ready", "submitted"}:
        raise RuntimeError("Cannot stage a transfer while queue outcome is pending")
    state: HandoffStateRecord = {
        "phase": "ready",
        "created_at": preparation["created_at"],
        "source_turn_id": preparation["source_turn_id"],
        "prompt": preparation["prompt"],
        "prompt_digest": preparation["prompt_digest"],
        "target_model": preparation["target_model"],
        "target_effort": preparation["target_effort"],
        "official_source_url": required_text(preparation["official_source_url"]),
        "official_guidance": required_text(preparation["official_guidance"]),
        "task_inference": required_text(preparation["task_inference"]),
    }
    if "control_turn_id" in preparation:
        state["control_turn_id"] = preparation["control_turn_id"]
    if "continuation_turn_ids" in preparation:
        state["continuation_turn_ids"] = preparation["continuation_turn_ids"]
    return _save(slot, state)


def continue_transfer(
    slot: TransferStateSlot, state: HandoffStateRecord, turn_id: str
) -> None:
    if state["phase"] not in {"ready", "queued"}:
        raise RuntimeError("Only a prepared transfer accepts a control turn")
    state["control_turn_id"] = turn_id
    if turn_id != state["source_turn_id"]:
        continuations = state.setdefault("continuation_turn_ids", [])
        if turn_id not in continuations:
            continuations.append(turn_id)
    _save(slot, state)


def bind_replay(
    slot: TransferStateSlot, state: HandoffStateRecord, turn_id: str
) -> None:
    if state["phase"] != "queued" or state.get("replay_turn_id") not in (None, turn_id):
        raise RuntimeError("Replay does not belong to this queued transfer")
    state.pop("pending_assessment", None)
    state["replay_turn_id"] = turn_id
    _save(slot, state)


def begin_queue(slot: TransferStateSlot, state: HandoffStateRecord) -> None:
    if state["phase"] != "ready":
        raise RuntimeError("Only a prepared transfer can enter the queue")
    state["phase"] = "attempting"
    _save(slot, state)


def receipt(
    slot: TransferStateSlot, state: HandoffStateRecord, submission_id: str
) -> None:
    if state["phase"] != "attempting":
        raise RuntimeError("Queue receipt requires an active attempt")
    state["queued_submission_id"] = submission_id
    _save(slot, state)


def reject(slot: TransferStateSlot, state: HandoffStateRecord) -> None:
    if state["phase"] != "attempting":
        raise RuntimeError("Only an attempted transfer can be rejected")
    state["phase"] = "rejected"
    _save(slot, state)


def confirm_queue(
    slot: TransferStateSlot, state: HandoffStateRecord, timestamp: float
) -> None:
    if state["phase"] != "attempting" or not state.get("queued_submission_id"):
        raise RuntimeError("Queue confirmation requires its native receipt")
    state["phase"] = "queued"
    state["queued_at"] = int(timestamp)
    _save(slot, state)


def release(slot: TransferStateSlot) -> None:
    current = slot.load()
    if current is not None and current["phase"] == "attempting":
        raise RuntimeError("An unresolved queue attempt cannot be released")
    pending = current.get("pending_assessment") if current is not None else None
    if pending:
        _save(
            slot,
            {
                "phase": "submitted",
                "source_turn_id": pending["turn_id"],
                "pending_assessment": pending,
            },
        )
    else:
        slot.clear()
