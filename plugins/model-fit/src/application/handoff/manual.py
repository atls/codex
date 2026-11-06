from typing import Any, Callable

from model_fit.application.assessment.validation import RECOMMENDATIONS
from model_fit.application.handoff.ports.pending import Pending
from model_fit.application.handoff.ports.presentation import Presentation
from model_fit.application.handoff.recommendation import recommended_profile


def decide(
    request: dict[str, Any],
    *,
    recommendation: Pending,
    assessor: Callable,
    presentation: Presentation,
    digest: Callable[[str], str],
    observe: Callable[[str], None] | None = None,
):
    pending = recommendation.load()
    if pending is not None and pending["prompt_hash"] != digest(request["task"]):
        try:
            recommendation.clear()
        except OSError:
            if observe is not None:
                observe("blocked_state_error")
            return presentation.block(
                "Model Fit: не удалось сбросить рекомендацию для предыдущего запроса. Повтори запрос после восстановления локального состояния hook."
            )
        pending = None
    if pending is not None and pending["prompt_hash"] == digest(request["task"]):
        if pending["active_profile"] == request["active_profile"]:
            if observe is not None:
                observe("cached_" + pending["result"]["decision"])
            return presentation.hook_output(pending["result"])
        if recommended_profile(pending) == request["active_profile"]:
            recommendation.clear(missing_ok=True)
            if observe is not None:
                observe("selected")
            return None
    result = assessor(request)
    if observe is not None:
        observe(result["decision"])
    output = presentation.hook_output(result)
    if result["decision"] in RECOMMENDATIONS:
        try:
            recommendation.save(request, result)
        except OSError:
            if observe is not None:
                observe("pending_save_error")
            assert output is not None and presentation.is_block(output)
            presentation.extend_reason(
                output,
                " Состояние паузы не сохранилось; при повторе проверка запустится заново.",
            )
    elif result["decision"] == "keep":
        recommendation.clear(missing_ok=True)
    return output
