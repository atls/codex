from vector_prime.application.assessment.types.decision import AssessmentDecision
from vector_prime.application.assessment.types.evidence import (
    RecommendationEvidence,
)
from vector_prime.application.assessment.guards.recommendation import (
    require_recommendation,
)
from vector_prime.application.switch.types.disposition import BlockedTurn
from vector_prime.application.switch.types.disposition import ContinueWork
from vector_prime.application.switch.types.disposition import ManualRecommendation
from vector_prime.application.switch.types.disposition import TurnDisposition
from vector_prime.application.assessment.types.result import UnknownAssessment
from vector_prime.application.switch.types.disposition import TurnNotice
from vector_prime.application.switch.types.disposition import WorkContext


def assessment_disposition(
    evidence: AssessmentDecision | RecommendationEvidence,
) -> ManualRecommendation | UnknownAssessment | None:
    if evidence["decision"] == "keep":
        return None
    if evidence["decision"] == "unknown":
        return UnknownAssessment()
    require_recommendation(evidence)
    return ManualRecommendation(evidence)


def blocks_work(result: TurnDisposition) -> bool:
    return isinstance(result, (BlockedTurn, ManualRecommendation))


def assessment_audit_outcome(result: TurnDisposition | None) -> str:
    if result is None:
        return "auto_pass"
    if isinstance(result, ContinueWork):
        if result.context is WorkContext.TRANSFER_CANCELLED:
            return (
                "auto_unknown"
                if isinstance(result.preceding, UnknownAssessment)
                else "auto_pass"
            )
        if result.context is WorkContext.REPLAY:
            return "auto_replay"
        return "auto_handoff"
    if blocks_work(result):
        return "auto_block"
    if isinstance(result, (UnknownAssessment, TurnNotice)):
        return "auto_unknown"
    return "auto_handoff"
