"""Refine supported stored projections before executing phase-specific effects."""

from vector_prime.application.handoff.exceptions.invalid_handoff import InvalidHandoff
from vector_prime.application.handoff.types.plan import TransferTarget
from vector_prime.application.handoff.types.progress import (
    AttemptedHandoff,
    PreparedHandoff,
    QueuedHandoff,
    TransferInputEvidence,
)
from vector_prime.application.switch.types.state import ProcessSnapshot


def prepared_handoff(state: ProcessSnapshot) -> PreparedHandoff:
    if state["phase"] != "ready":
        raise InvalidHandoff("invalid_state")
    try:
        return PreparedHandoff(
            state["source_turn_id"],
            TransferTarget(state["target_model"], state["target_effort"]),
            state["created_at"],
            state.get("transfer_authorized_at", state["created_at"]),
            state["prompt"],
            state["prompt_digest"],
        )
    except KeyError:
        raise InvalidHandoff("invalid_state") from None


def transfer_input_evidence(state: ProcessSnapshot) -> TransferInputEvidence:
    if "queued_input_digest" in state:
        return TransferInputEvidence("native_input", state["queued_input_digest"])
    if "queued_prompt_digest" in state:
        return TransferInputEvidence("legacy_prompt", state["queued_prompt_digest"])
    raise InvalidHandoff("invalid_state")


def attempted_handoff(state: ProcessSnapshot) -> AttemptedHandoff:
    if state["phase"] != "attempting":
        raise InvalidHandoff("invalid_state")
    try:
        return AttemptedHandoff(
            state["source_turn_id"],
            TransferTarget(state["target_model"], state["target_effort"]),
            state["queued_client_message_id"],
            transfer_input_evidence(state),
            state.get("queued_submission_id"),
        )
    except KeyError:
        raise InvalidHandoff("invalid_state") from None


def queued_handoff(state: ProcessSnapshot) -> QueuedHandoff:
    if state["phase"] != "queued":
        raise InvalidHandoff("invalid_state")
    try:
        return QueuedHandoff(
            state["source_turn_id"],
            TransferTarget(state["target_model"], state["target_effort"]),
            state["queued_submission_id"],
            transfer_input_evidence(state),
            state.get("replay_turn_id"),
        )
    except KeyError:
        raise InvalidHandoff("invalid_state") from None
