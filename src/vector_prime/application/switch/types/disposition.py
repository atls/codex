from vector_prime.application.assessment.types.result import UnknownAssessment
from dataclasses import dataclass
from enum import Enum

from vector_prime.application.assessment.types.decision import AssessmentDecision
from vector_prime.application.assessment.types.evidence import (
    RecommendationEvidence,
)
from vector_prime.application.handoff.types.instruction import TransferInstruction


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
    instruction: TransferInstruction


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
