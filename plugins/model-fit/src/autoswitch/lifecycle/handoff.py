from __future__ import annotations
from model_fit.assessment.types.decision import AssessmentDecision
from model_fit.assessment.types.profile import ActiveProfile
from model_fit.autoswitch.lifecycle.types.plan import ManualHandoff, TransferTarget

from model_fit.assessment.decoding import required_text
from model_fit.autoswitch.state.types.preparation import TransferPreparation
from model_fit.autoswitch.state.types.record import HandoffStateRecord

from model_fit.autoswitch.state.types.storage import TransferStateSlot

from model_fit.autoswitch.state.commit import save_snapshot
from model_fit.autoswitch.handoff.types.queue_receipt import NativeQueueReceipt
from model_fit.native_input.types.json import JsonValue
from model_fit.native_input import codec
from model_fit.autoswitch.exceptions.invalid_handoff import InvalidHandoff
from model_fit.autoswitch.exceptions.handoff_conflict import HandoffConflict
from model_fit.autoswitch.state.decoding import (
    prepared_handoff,
    attempted_handoff,
    queued_handoff,
)
from model_fit.autoswitch.lifecycle.types.progress import PreparedHandoff
from model_fit.autoswitch.lifecycle.types.progress import QueuedHandoff
from model_fit.autoswitch.types.queue import QueueConfirmation
from model_fit.autoswitch.handoff.expiry import HANDOFF_TTL_SECONDS


def require_queue_executor(caller_thread: str | None, thread_id: str) -> None:
    if caller_thread and caller_thread != thread_id:
        raise InvalidHandoff("foreign_executor")


def queue_preparation(
    state: HandoffStateRecord | None, source_turn_id: str, now: float
) -> PreparedHandoff | QueueConfirmation:
    if state is None or state["source_turn_id"] != source_turn_id:
        raise InvalidHandoff("not_prepared")
    if state["phase"] == "queued":
        if not state.get("queued_submission_id"):
            raise InvalidHandoff("invalid_state")
        return QueueConfirmation(state["queued_submission_id"], already_confirmed=True)
    if state.get("pending_assessment") is not None:
        raise HandoffConflict("pending_assessment")
    if state["phase"] == "rejected":
        raise HandoffConflict("rejected")
    if state["phase"] != "ready":
        raise HandoffConflict("outcome_unknown")
    prepared = prepared_handoff(state)
    if now - prepared.authorized_at > HANDOFF_TTL_SECONDS:
        raise InvalidHandoff("expired")
    return prepared


def require_transfer_profile(
    prepared: PreparedHandoff, selected: tuple[str | None, str | None]
) -> None:
    if selected != (prepared.target.model, prepared.target.effort):
        raise InvalidHandoff("profile_not_applied")


def plan_transfer(
    result: AssessmentDecision, active: ActiveProfile, *, child_agent: bool
) -> TransferTarget | ManualHandoff:
    if child_agent:
        return ManualHandoff(
            "child_profile_allocation_required",
            " Automatic child-agent handoff is not performed; pass the recommendation to the parent agent to choose the profile when allocating the work.",
            retain_profile_context=False,
        )
    if result.get("recommended_speed") not in (None, active["speed"]):
        return ManualHandoff(
            "speed_switch_unsupported",
            f" Automatic speed-tier handoff is unavailable; requested value: {result['recommended_speed']}.",
        )
    target = TransferTarget(
        result.get("recommended_model") or result["active_model"],
        result.get("recommended_effort") or result["active_effort"],
    )
    if (target.model, target.effort) == (
        result["active_model"],
        result["active_effort"],
    ):
        return ManualHandoff("no_model_or_effort_change")
    return target


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


def authorize_transfer(
    slot: TransferStateSlot, state: HandoffStateRecord, now: float
) -> None:
    save_snapshot(slot, {**state, "transfer_authorized_at": now})


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
    return save_snapshot(slot, state)


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
    save_snapshot(slot, state)


def bind_replay(
    slot: TransferStateSlot, state: HandoffStateRecord, turn_id: str
) -> None:
    queued = queued_handoff(state)
    if queued.replay_turn_id not in (None, turn_id):
        raise RuntimeError("Replay does not belong to this queued transfer")
    state.pop("pending_assessment", None)
    state["replay_turn_id"] = turn_id
    save_snapshot(slot, state)


def begin_queue(
    slot: TransferStateSlot,
    state: HandoffStateRecord,
    client_message_id: str,
    content: list[dict[str, JsonValue]],
) -> None:
    prepared_handoff(state)
    state["queued_client_message_id"] = client_message_id
    state.pop("prompt")
    state["source_input_digest"] = codec.input_digest(content)
    state["queued_input_digest"] = codec.input_digest(content)
    state["queued_prompt_digest"] = codec.prompt_digest(codec.input_text(content))
    state["queued_hook_prompt_digest"] = codec.prompt_digest(codec.hook_prompt(content))
    state["phase"] = "attempting"
    save_snapshot(slot, state)


def receipt(
    slot: TransferStateSlot, state: HandoffStateRecord, submission: NativeQueueReceipt
) -> None:
    attempted_handoff(state)
    state["queued_submission_id"] = submission.submission_id
    # A native acknowledgement must survive malformed content: retrying an
    # externally accepted submission is unsafe even when its payload is unknown.
    save_snapshot(slot, state)
    if not submission.accepted_input:
        raise ValueError("Native queue receipt input is unavailable")
    state["queued_input_digest"] = codec.input_digest(submission.accepted_input)
    save_snapshot(slot, state)


def reject(slot: TransferStateSlot, state: HandoffStateRecord) -> None:
    if state["phase"] != "attempting":
        raise RuntimeError("Only an attempted transfer can be rejected")
    state["phase"] = "rejected"
    save_snapshot(slot, state)


def confirm_queue(
    slot: TransferStateSlot, state: HandoffStateRecord, timestamp: float
) -> QueuedHandoff:
    attempt = attempted_handoff(state)
    if not attempt.submission_id:
        raise RuntimeError("Queue confirmation requires its native receipt")
    state["phase"] = "queued"
    state["queued_at"] = int(timestamp)
    save_snapshot(slot, state)
    return QueuedHandoff(
        attempt.source_turn_id,
        attempt.target,
        attempt.submission_id,
        attempt.input_evidence,
        None,
    )


def release(slot: TransferStateSlot) -> None:
    current = slot.load()
    if current is not None and current["phase"] == "attempting":
        raise RuntimeError("An unresolved queue attempt cannot be released")
    pending = current.get("pending_assessment") if current is not None else None
    if pending:
        save_snapshot(
            slot,
            {
                "phase": "submitted",
                "source_turn_id": pending["turn_id"],
                "pending_assessment": pending,
            },
        )
    else:
        slot.clear()
