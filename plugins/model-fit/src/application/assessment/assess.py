"""Run an isolated Model Fit preflight and return one validated decision."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from model_fit.application.assessment.contracts.decision import Decision
from model_fit.application.assessment.contracts.request import AssessmentRequest
from model_fit.application.assessment.ports.catalog import Catalog
from model_fit.application.assessment.ports.evaluator import Evaluator
from model_fit.application.assessment.ports.sources import Sources
from model_fit.application.assessment.prompt import assessment_prompt
from model_fit.application.assessment.validation import (
    empty_decision,
    validate,
    validated_request,
)


def assess(
    request: AssessmentRequest,
    evaluator_model: str,
    evaluator_effort: str,
    timeout: int,
    source_bundle: tuple[str, Catalog] | None = None,
    diagnostics: dict[str, Any] | None = None,
    *,
    source_reader: Sources,
    evaluator: Evaluator,
) -> Decision:
    task, active, context, prior = validated_request(request)
    if prior is not None:
        if diagnostics is not None:
            diagnostics.update(
                {
                    "prompt_sha256": hashlib.sha256(
                        json.dumps(request, sort_keys=True, ensure_ascii=False).encode()
                    ).hexdigest(),
                    "user_choice_bypass": True,
                    "agent_messages": 0,
                    "skill_item_seen": False,
                    "tool_types": [],
                    "events": [{"event": "confirmed_user_choice_bypass"}],
                    "usage": None,
                }
            )
        return cast(
            Decision,
            empty_decision(
                active,
                "keep",
                "Пользователь уже выбрал текущий профиль для той же работы",
            ),
        )
    source_text, models = (
        source_bundle if source_bundle is not None else source_reader()
    )
    if not models.supported(active):
        raise ValueError("Active profile is absent from the local catalog")
    if not models.supported(
        {"model": evaluator_model, "effort": evaluator_effort, "speed": None}
    ):
        raise ValueError("Evaluator profile is absent from the local catalog")
    instructions, prompt = assessment_prompt(task, active, context, source_text)
    if diagnostics is not None:
        diagnostics["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
    if "input" in request:
        output = evaluator(
            instructions,
            prompt,
            evaluator_model,
            evaluator_effort,
            timeout,
            diagnostics,
            native_input=request["input"],
        )
    else:
        output = evaluator(
            instructions,
            prompt,
            evaluator_model,
            evaluator_effort,
            timeout,
            diagnostics,
        )
    return cast(Decision, validate(output, active, models))
