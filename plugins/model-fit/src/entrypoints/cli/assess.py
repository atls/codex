"""CLI for one isolated Model Fit profile assessment."""

from __future__ import annotations

from pathlib import Path
from model_fit.assessment.types.catalog import ProfileCatalog
from model_fit.assessment.types.request import ProfileAssessmentInput
from model_fit.assessment.types.decision import AssessmentDecision
from model_fit.native_input.types.json import JsonValue
from model_fit.infrastructure.adapters.codex.transport.assessment.session import (
    AppServer,
)
import argparse
import json
import subprocess
import sys

from model_fit.assessment.assess import assess as assess_profile
from model_fit.infrastructure.adapters.codex.sources import assessment_sources
from model_fit.infrastructure.adapters.codex.assessment import native_evaluator
from model_fit.infrastructure.adapters.codex.catalog import NativeCatalog
from model_fit.assessment.exceptions.source_unavailable import SourceUnavailable
from model_fit.assessment.validation import empty_decision, validated_request


def assess(
    request: ProfileAssessmentInput,
    evaluator_model: str,
    evaluator_effort: str,
    timeout: int,
    source_bundle: tuple[str, ProfileCatalog | dict[str, dict[str, JsonValue]]]
    | None = None,
    diagnostics: dict[str, JsonValue] | None = None,
    *,
    codex_path: str = "codex",
    runtime_factory: type[AppServer] | None = None,
    skill_directory: Path | None = None,
) -> AssessmentDecision:
    if source_bundle is not None and isinstance(source_bundle[1], dict):
        source_bundle = (source_bundle[0], NativeCatalog(source_bundle[1]))
    sources: tuple[str, ProfileCatalog] | None = None
    if source_bundle is not None:
        source_text, catalog = source_bundle
        sources = (
            source_text,
            NativeCatalog(catalog) if isinstance(catalog, dict) else catalog,
        )
    return assess_profile(
        request,
        evaluator_model,
        evaluator_effort,
        timeout,
        sources,
        diagnostics,
        source_reader=assessment_sources,
        evaluator=native_evaluator(
            request, codex_path, runtime_factory, skill_directory
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        "--evaluator-model",
        default="gpt-6.1-sol",
        help="Model used by the evaluator; active profile belongs in the JSON input",
    )
    parser.add_argument(
        "--effort",
        "--evaluator-effort",
        default="low",
        help="Evaluator reasoning effort",
    )
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin)
        _, active, _, _ = validated_request(request)
    except (ValueError, TypeError) as error:
        print(f"model-fit triage input error: {type(error).__name__}", file=sys.stderr)
        return 2
    try:
        result = assess(request, args.model, args.effort, args.timeout)
    except SourceUnavailable as error:
        print(f"model-fit triage error: {type(error).__name__}", file=sys.stderr)
        result = empty_decision(
            active, "unknown", "A required assessment source is unavailable"
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        TimeoutError,
        subprocess.SubprocessError,
        KeyError,
    ) as error:
        print(f"model-fit triage error: {type(error).__name__}", file=sys.stderr)
        result = empty_decision(
            active, "unknown", "Triage did not return a validated decision"
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["decision"] != "unknown" else 1


if __name__ == "__main__":
    sys.exit(main())
