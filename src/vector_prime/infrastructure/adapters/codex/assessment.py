"""Bind the native Codex evaluator to the assessment port."""

from pathlib import Path

from vector_prime.application.assessment.types.evaluator import AssessmentEvaluator
from vector_prime.application.assessment.types.request import ProfileAssessmentInput
from vector_prime.application.submission.types.json import JsonValue
from vector_prime.infrastructure.adapters.codex.transport.assessment.session import (
    AppServer,
)
from vector_prime.infrastructure.adapters.codex.transport.assessment.types.runtime import (
    AssessmentRuntimeFactory,
)


def native_evaluator(
    request: ProfileAssessmentInput,
    codex_path: str,
    runtime_factory: AssessmentRuntimeFactory | None,
    skill_directory: Path | None,
) -> AssessmentEvaluator:
    from vector_prime.infrastructure.adapters.codex.transport.assessment.execution import (
        execute_assessment,
    )

    def evaluate(
        instructions: str,
        prompt: str,
        model: str,
        effort: str,
        timeout: int,
        diagnostics: dict[str, JsonValue] | None,
        *,
        native_input: list[dict[str, JsonValue]] | None = None,
    ) -> object:
        return execute_assessment(
            instructions,
            prompt,
            model,
            effort,
            timeout,
            diagnostics,
            codex_path,
            runtime_factory or AppServer,
            skill_directory,
            native_input=native_input,
            active_profile=request["active_profile"],
        )

    return evaluate
