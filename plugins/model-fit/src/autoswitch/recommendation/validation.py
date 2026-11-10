from typing import Any

from model_fit.assessment.validation import RECOMMENDATIONS


def require_recommendation(result: dict[str, Any]) -> None:
    if result["decision"] not in RECOMMENDATIONS:
        raise ValueError("Blocking recommendation is unavailable")
    model = result.get("recommended_model") or result["active_model"]
    effort = result.get("recommended_effort") or result["active_effort"]
    source = result.get("official_source_url")
    guidance = result.get("official_guidance")
    inference = result.get("task_inference")
    if not all(
        (
            isinstance(value, str) and value
            for value in (model, effort, source, guidance, inference)
        )
    ):
        raise ValueError("Incomplete triage recommendation")
