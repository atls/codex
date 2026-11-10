from dataclasses import dataclass

from model_fit.application.switch.state.types.record import HandoffStateRecord


@dataclass(frozen=True)
class ReconciledAssessment:
    pending_transfer: HandoffStateRecord | None
    snapshot: HandoffStateRecord | None
    profile_context_turn_id: str | None
    profile_context_state: HandoffStateRecord | None
    fresh_session: bool
