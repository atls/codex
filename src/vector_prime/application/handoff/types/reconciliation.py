from dataclasses import dataclass

from vector_prime.application.switch.types.state import ProcessSnapshot


@dataclass(frozen=True)
class ReconciledHandoff:
    pending_transfer: ProcessSnapshot | None
