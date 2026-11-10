from model_fit.application.assessment.types.result import UnknownAssessment
from dataclasses import dataclass
from enum import Enum

from model_fit.application.assessment.types.decision import AssessmentDecision
from model_fit.application.assessment.types.evidence import (
    RecommendationEvidence,
)
from model_fit.application.switch.state.types.record import HandoffStateRecord


class WorkContext(Enum):
    ASSESSED = "assessed"
    REPLAY = "replay"
    TRANSFER_CANCELLED = "transfer_cancelled"


@dataclass(frozen=True)
class BlockedTurn:
    reason: str


@dataclass(frozen=True)
class TurnNotice:
    message: str


@dataclass
class ManualRecommendation:
    evidence: AssessmentDecision | RecommendationEvidence
    explanation: str = ""


@dataclass(frozen=True)
class ContinueWork:
    context: WorkContext | str
    preceding: "TurnDisposition | None" = None


@dataclass(frozen=True)
class AssessmentPending:
    pass


@dataclass(frozen=True)
class QueuePending:
    pass


@dataclass(frozen=True)
class PreparedTransfer:
    thread_id: str
    turn_id: str
    state: HandoffStateRecord


@dataclass(frozen=True)
class UnrelatedAnswer:
    pass


TurnDisposition = (
    BlockedTurn
    | TurnNotice
    | UnknownAssessment
    | ManualRecommendation
    | ContinueWork
    | AssessmentPending
    | QueuePending
    | PreparedTransfer
    | UnrelatedAnswer
)
