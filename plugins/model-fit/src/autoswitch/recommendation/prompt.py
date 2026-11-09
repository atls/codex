from __future__ import annotations

from typing import Any, Callable

from model_fit.assessment.validation import RECOMMENDATIONS
from model_fit.autoswitch.recommendation.types.protocols.storage import (
    RecommendationStore,
)
from model_fit.autoswitch.types.protocols.output import HookOutputRenderer
from model_fit.autoswitch.recommendation.check import recommended_profile


def decide(
    request: dict[str, Any],
    *,
    thread_id: str,
    recommendations: RecommendationStore,
    assessor: Callable,
    presentation: HookOutputRenderer,
    digest: Callable[[str], str],
    observe: Callable[[str], None] | None = None,
):
    pending = recommendations.load(thread_id)
    if pending is not None and pending["prompt_hash"] != digest(request["task"]):
        try:
            recommendations.clear(thread_id)
        except OSError:
            if observe is not None:
                observe("blocked_state_error")
            return presentation.block(
                "Model Fit: the previous request's recommendation could not be cleared. Repeat the request after restoring local hook state."
            )
        pending = None
    if pending is not None and pending["prompt_hash"] == digest(request["task"]):
        if pending["active_profile"] == request["active_profile"]:
            if observe is not None:
                observe("cached_" + pending["result"]["decision"])
            return presentation.hook_output(pending["result"])
        if recommended_profile(pending) == request["active_profile"]:
            recommendations.clear(thread_id, missing_ok=True)
            if observe is not None:
                observe("selected")
            return None
    result = assessor(request)
    if observe is not None:
        observe(result["decision"])
    output = presentation.hook_output(result)
    if result["decision"] in RECOMMENDATIONS:
        try:
            recommendations.save(thread_id, request, result)
        except OSError:
            if observe is not None:
                observe("pending_save_error")
            assert output is not None and presentation.is_block(output)
            presentation.extend_reason(
                output,
                " The pause state could not be saved; a retry will start assessment again.",
            )
    elif result["decision"] == "keep":
        recommendations.clear(thread_id, missing_ok=True)
    return output
