from __future__ import annotations

from vector_prime.application.switch.types.state import ProcessSnapshot
from vector_prime.application.handoff.exceptions.invalid_handoff import InvalidHandoff
from vector_prime.application.handoff.exceptions.conflict import HandoffConflict
from vector_prime.application.handoff.helpers.progress import (
    prepared_handoff,
)
from vector_prime.application.handoff.types.progress import PreparedHandoff
from vector_prime.application.handoff.types.queue import QueueConfirmation


HANDOFF_TTL_SECONDS = 300


def require_rejection_state(state: ProcessSnapshot) -> None:
    if state["phase"] != "attempting":
        raise RuntimeError("Only an attempted transfer can be rejected")


def require_release_state(state: ProcessSnapshot | None) -> None:
    if state is not None and state["phase"] == "attempting":
        raise RuntimeError("An unresolved queue attempt cannot be released")


def queue_preparation(
    state: ProcessSnapshot | None, source_turn_id: str, now: float
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
