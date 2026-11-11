from dataclasses import dataclass

from vector_prime.application.handoff.types.progress import PreparedHandoff
from vector_prime.application.handoff.types.source import HandoffSource


@dataclass(frozen=True)
class QueueConfirmation:
    submission_id: str
    already_confirmed: bool = False


@dataclass(frozen=True)
class PreparedQueue:
    transfer: PreparedHandoff
    source: HandoffSource
