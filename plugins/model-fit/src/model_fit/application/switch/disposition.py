from model_fit.application.assessment.types.decision import AssessmentDecision
from model_fit.application.switch.recommendation.types.evidence import (
    RecommendationEvidence,
)
from model_fit.application.switch.recommendation.validation import (
    require_recommendation,
)
from model_fit.application.switch.types.disposition import (
    BlockedTurn,
    ContinueWork,
    ManualRecommendation,
    TurnDisposition,
    UnknownAssessment,
    TurnNotice,
    WorkContext,
)


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
