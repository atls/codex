from dataclasses import dataclass

from model_fit.application.switch.types.state import ProcessSnapshot


@dataclass(frozen=True)
class ReconciledSubmission:
    pending_transfer: ProcessSnapshot | None
    snapshot: ProcessSnapshot | None
    profile_context_turn_id: str | None
    profile_context_state: ProcessSnapshot | None
    fresh_session: bool
