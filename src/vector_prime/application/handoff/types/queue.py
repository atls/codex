from dataclasses import dataclass

from vector_prime.application.handoff.types.progress import PreparedHandoff
from vector_prime.application.handoff.types.source import HandoffSource
from vector_prime.application.handoff.types.state import TransferState


@dataclass(frozen=True)
class QueueConfirmation:
    submission_id: str
    already_confirmed: bool = False


@dataclass(frozen=True)
class PreparedQueue:
    transfer: PreparedHandoff
    source: HandoffSource


@dataclass(frozen=True)
class QueueCandidate:
    source_turn_id: str
    pending_assessment: bool
    transfer: TransferState | None
