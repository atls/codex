from dataclasses import dataclass

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
