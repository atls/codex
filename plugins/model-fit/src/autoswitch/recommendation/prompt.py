from __future__ import annotations

from typing import Callable

from model_fit.assessment.validation import RECOMMENDATIONS
from model_fit.assessment.types.request import ProfileAssessmentInput
from model_fit.submission.types.evaluation import AssessmentRunner
from model_fit.autoswitch.recommendation.types.storage import (
    RecommendationStore,
)
from model_fit.autoswitch.types.disposition import (
    BlockedTurn,
    ManualRecommendation,
    TurnDisposition,
)
from model_fit.autoswitch.disposition import assessment_disposition

from model_fit.autoswitch.recommendation.check import recommended_profile


def decide(
    request: ProfileAssessmentInput,
    *,
    thread_id: str,
    recommendations: RecommendationStore,
    assessor: AssessmentRunner,
    digest: Callable[[str], str],
    observe: Callable[[str], bool | None] | None = None,
) -> TurnDisposition | None:
    pending = recommendations.load(thread_id)
    if pending is not None and pending["prompt_hash"] != digest(request["task"]):
        try:
            recommendations.clear(thread_id)
        except OSError:
            if observe is not None:
                observe("blocked_state_error")
            return BlockedTurn(
                "Model Fit: the previous request's recommendation could not be cleared. Repeat the request after restoring local hook state."
            )
        pending = None
    if pending is not None and pending["prompt_hash"] == digest(request["task"]):
        if pending["active_profile"] == request["active_profile"]:
            if observe is not None:
                observe("cached_" + pending["result"]["decision"])
            return assessment_disposition(pending["result"])
        if recommended_profile(pending) == request["active_profile"]:
            recommendations.clear(thread_id, missing_ok=True)
            if observe is not None:
                observe("selected")
            return None
    result = assessor(request)
    if observe is not None:
        observe(result["decision"])
    output = assessment_disposition(result)
    if result["decision"] in RECOMMENDATIONS:
        try:
            recommendations.save(thread_id, request, result)
        except OSError:
            if observe is not None:
                observe("pending_save_error")
            assert isinstance(output, ManualRecommendation)
            output.explanation += " The pause state could not be saved; a retry will start assessment again."
    elif result["decision"] == "keep":
        recommendations.clear(thread_id, missing_ok=True)
    return output
