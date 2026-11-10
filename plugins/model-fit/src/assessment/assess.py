"""Run an isolated Model Fit preflight and return one validated decision."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from model_fit.assessment.types.catalog import ProfileCatalog
from model_fit.assessment.types.decision import AssessmentDecision
from model_fit.assessment.types.evaluator import AssessmentEvaluator
from model_fit.assessment.types.request import ProfileAssessmentInput
from model_fit.assessment.types.sources import AssessmentSources
from model_fit.assessment.prompt import assessment_prompt
from model_fit.assessment.validation import empty_decision, validate, validated_request


def assess(
    request: ProfileAssessmentInput,
    evaluator_model: str,
    evaluator_effort: str,
    timeout: int,
    source_bundle: tuple[str, ProfileCatalog] | None = None,
    diagnostics: dict[str, Any] | None = None,
    *,
    source_reader: AssessmentSources,
    evaluator: AssessmentEvaluator,
) -> AssessmentDecision:
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
            AssessmentDecision,
            empty_decision(
                active,
                "keep",
                "The user already selected the active profile for the same work",
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
    return cast(AssessmentDecision, validate(output, active, models))
