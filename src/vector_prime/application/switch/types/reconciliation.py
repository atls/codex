from dataclasses import dataclass
from vector_prime.application.handoff.types.preparation import TransferContinuation

from vector_prime.application.switch.types.state import ProcessSnapshot


@dataclass(frozen=True)
class ReconciledSubmission:
    pending_transfer: TransferContinuation | None
    snapshot: ProcessSnapshot | None
    profile_context_turn_id: str | None
    profile_context_state: ProcessSnapshot | None
    fresh_session: bool
