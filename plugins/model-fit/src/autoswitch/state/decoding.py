"""Refine supported stored projections before executing phase-specific effects."""

from model_fit.autoswitch.exceptions.invalid_handoff import InvalidHandoff
from model_fit.autoswitch.lifecycle.types.plan import TransferTarget
from model_fit.autoswitch.lifecycle.types.progress import (
    AttemptedHandoff,
    PreparedHandoff,
    QueuedHandoff,
    TransferInputEvidence,
)
from model_fit.autoswitch.state.types.record import HandoffStateRecord


def prepared_handoff(state: HandoffStateRecord) -> PreparedHandoff:
    if state["phase"] != "ready" or not all(
        field in state
        for field in (
            "target_model",
            "target_effort",
            "created_at",
            "prompt",
            "prompt_digest",
        )
    ):
        raise InvalidHandoff("invalid_state")
    return PreparedHandoff(
        state["source_turn_id"],
        TransferTarget(state["target_model"], state["target_effort"]),
        state["created_at"],
        state.get("transfer_authorized_at", state["created_at"]),
        state["prompt"],
        state["prompt_digest"],
    )


def transfer_input_evidence(state: HandoffStateRecord) -> TransferInputEvidence:
    if "queued_input_digest" in state:
        return TransferInputEvidence("native_input", state["queued_input_digest"])
    if "queued_prompt_digest" in state:
        return TransferInputEvidence("legacy_prompt", state["queued_prompt_digest"])
    raise InvalidHandoff("invalid_state")


def attempted_handoff(state: HandoffStateRecord) -> AttemptedHandoff:
    if state["phase"] != "attempting" or not all(
        field in state
        for field in ("target_model", "target_effort", "queued_client_message_id")
    ):
        raise InvalidHandoff("invalid_state")
    return AttemptedHandoff(
        state["source_turn_id"],
        TransferTarget(state["target_model"], state["target_effort"]),
        state["queued_client_message_id"],
        transfer_input_evidence(state),
        state.get("queued_submission_id"),
    )


def queued_handoff(state: HandoffStateRecord) -> QueuedHandoff:
    if state["phase"] != "queued" or not all(
        field in state
        for field in ("target_model", "target_effort", "queued_submission_id")
    ):
        raise InvalidHandoff("invalid_state")
    return QueuedHandoff(
        state["source_turn_id"],
        TransferTarget(state["target_model"], state["target_effort"]),
        state["queued_submission_id"],
        transfer_input_evidence(state),
        state.get("replay_turn_id"),
    )
