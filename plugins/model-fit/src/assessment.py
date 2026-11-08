"""Standalone assessment composition without Desktop hook dependencies."""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from model_fit.application.assessment.assess import assess as assess_profile
from model_fit.application.assessment.contracts.decision import Decision
from model_fit.application.assessment.contracts.request import AssessmentRequest
from model_fit.infrastructure.assessment.preflight.execution import execute_assessment
from model_fit.infrastructure.assessment.preflight.session import AppServer
from model_fit.infrastructure.assessment.sources.catalog import NativeCatalog
from model_fit.infrastructure.assessment.sources.reader import sources


def assess(
    request: AssessmentRequest,
    evaluator_model: str,
    evaluator_effort: str,
    timeout: int,
    source_bundle=None,
    diagnostics=None,
    codex_path: str = "codex",
    runtime_factory: Callable[..., Any] | None = None,
    skill_directory: Path | None = None,
) -> Decision:
    """Assess task/context and optional original Codex UserInput items without projecting attachments."""

    def evaluate(
        instructions,
        prompt,
        model,
        effort,
        turn_timeout,
        observations,
        *,
        native_input=None,
    ):
        return execute_assessment(
            instructions,
            prompt,
            model,
            effort,
            turn_timeout,
            observations,
            codex_path,
            runtime_factory or AppServer,
            skill_directory,
            native_input=native_input,
            active_profile=request["active_profile"],
        )

    def read_sources():
        text, catalog = sources()
        return text, NativeCatalog(catalog) if isinstance(catalog, dict) else catalog

    if source_bundle is not None:
        text, catalog = source_bundle
        source_bundle = (
            text,
            NativeCatalog(catalog) if isinstance(catalog, dict) else catalog,
        )
    return assess_profile(
        request,
        evaluator_model,
        evaluator_effort,
        timeout,
        source_bundle,
        diagnostics,
        source_reader=read_sources,
        evaluator=evaluate,
    )
