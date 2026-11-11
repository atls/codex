from typing import Literal, Required

from typing_extensions import TypedDict

from vector_prime.application.assessment.types.profile import ActiveProfile
from vector_prime.application.assessment.types.state import PendingAssessment
from vector_prime.application.handoff.types.state import TransferState


class ProcessSnapshot(TypedDict, total=False):
    phase: Required[
        Literal["ready", "submitted", "attempting", "queued", "rejected", "passed"]
    ]
    source_turn_id: Required[str]
    assessment_generation: str | int
    pending_assessment: PendingAssessment | None
    assessment_decision: str
    profile_context_turn_id: str | None
    native_profile: ActiveProfile
    assessed_profile: ActiveProfile
    transfer: TransferState | None
    revision: str
