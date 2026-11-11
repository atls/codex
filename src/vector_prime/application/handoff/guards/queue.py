from vector_prime.application.handoff.exceptions.invalid_handoff import InvalidHandoff
from vector_prime.application.handoff.exceptions.conflict import HandoffConflict
from vector_prime.application.handoff.types.progress import PreparedHandoff
from vector_prime.application.handoff.types.queue import (
    QueueCandidate,
    QueueConfirmation,
)
from vector_prime.application.handoff.types.state import (
    AttemptingTransfer,
    QueuedTransfer,
    ReadyTransfer,
    RejectedTransfer,
    TransferState,
)

HANDOFF_TTL_SECONDS = 300


def require_rejection_state(state: TransferState | None) -> None:
    if not isinstance(state, AttemptingTransfer):
        raise RuntimeError("Only an attempted transfer can be rejected")


def queue_preparation(
    candidate: QueueCandidate | None, source_turn_id: str, now: float
) -> PreparedHandoff | QueueConfirmation:
    if candidate is None or candidate.source_turn_id != source_turn_id:
        raise InvalidHandoff("not_prepared")
    transfer = candidate.transfer
    if isinstance(transfer, QueuedTransfer):
        if not transfer.submission_id:
            raise InvalidHandoff("invalid_state")
        return QueueConfirmation(transfer.submission_id, already_confirmed=True)
    if candidate.pending_assessment:
        raise HandoffConflict("pending_assessment")
    if isinstance(transfer, RejectedTransfer):
        raise HandoffConflict("rejected")
    if not isinstance(transfer, ReadyTransfer):
        raise HandoffConflict("outcome_unknown")
    prepared = transfer.prepared
    if prepared is None:
        raise InvalidHandoff("invalid_state")
    if now - prepared.authorized_at > HANDOFF_TTL_SECONDS:
        raise InvalidHandoff("expired")
    return prepared
