from dataclasses import dataclass

from vector_prime.application.switch.types.state import ProcessSnapshot


@dataclass(frozen=True)
class ReconciledHandoff:
    pending_transfer: ProcessSnapshot | None


@dataclass(frozen=True)
class TransferContinued:
    """The prior transfer now belongs to the current control turn."""


@dataclass(frozen=True)
class ReconciliationDenied:
    reason: str
    reason_code: str | None = None
