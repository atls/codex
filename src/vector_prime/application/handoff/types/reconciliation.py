from dataclasses import dataclass
from enum import Enum

from vector_prime.application.handoff.types.preparation import TransferContinuation


@dataclass(frozen=True)
class ReconciledHandoff:
    pending_transfer: TransferContinuation | None


@dataclass(frozen=True)
class TransferContinued:
    """The prior transfer now belongs to the current control turn."""


@dataclass(frozen=True)
class ReconciliationDenied:
    reason: str
    reason_code: str | None = None


class TransferObservation(Enum):
    CONTINUED = "continued"
    STEERED = "steered"
    TERMINAL_SOURCE_WITHOUT_REPLAY = "terminal_source_without_replay"
