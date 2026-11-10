"""Invoke the profile assessment CLI and verify its response boundary."""

from __future__ import annotations

from pathlib import Path
from model_fit.assessment.types.evaluator import AssessmentEvaluator
from model_fit.native_input.types.json import JsonValue
from model_fit.infrastructure.adapters.codex.transport.assessment.session import (
    AppServer,
)
import json
import re
import subprocess
import sys

from model_fit.assessment.exceptions.source_unavailable import SourceUnavailable
from model_fit.assessment.exceptions.unknown_speed_change import UnknownSpeedChange
from model_fit.assessment.validation import RECOMMENDATIONS
from model_fit.assessment.types.request import ProfileAssessmentInput
from model_fit.assessment.types.decision import AssessmentDecision
from model_fit.assessment.decoding import decode_decision


def triage(request: ProfileAssessmentInput) -> AssessmentDecision:
    process = subprocess.run(
        [sys.executable, "-m", "model_fit.entrypoints.cli.assess", "--timeout", "45"],
        input=json.dumps(request, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=75,
    )
    failures = {
        "SourceUnavailable": SourceUnavailable,
        "TimeoutError": TimeoutError,
        "UnknownSpeedChange": UnknownSpeedChange,
        "ValueError": ValueError,
        "KeyError": KeyError,
        "TypeError": TypeError,
        "RuntimeError": RuntimeError,
        "OSError": OSError,
        "CalledProcessError": RuntimeError,
        "TimeoutExpired": TimeoutError,
    }
    diagnostic = re.search(
        "(?m)^model-fit triage (?:input )?error: ([A-Za-z][A-Za-z0-9_]{0,100})$",
        process.stderr,
    )
    if process.returncode != 0 and diagnostic:
        raise failures.get(diagnostic.group(1), RuntimeError)(
            "Assessment CLI did not return a verified allocation"
        )
    result = json.loads(process.stdout)
    if not isinstance(result, dict) or result.get("decision") not in RECOMMENDATIONS | {
        "keep",
        "unknown",
    }:
        raise ValueError("Triage returned an invalid decision")
    for field in ("model", "effort", "speed"):
        if result.get(f"active_{field}") != request["active_profile"][field]:
            raise ValueError("Triage changed the active profile")
    if process.returncode not in (0, 1) or (process.returncode == 1) != (
        result["decision"] == "unknown"
    ):
        raise ValueError("Triage exit status contradicts its decision")
    return decode_decision(result)


def native_evaluator(
    request: ProfileAssessmentInput,
    codex_path: str,
    runtime_factory: type[AppServer] | None,
    skill_directory: Path | None,
) -> AssessmentEvaluator:
    from model_fit.infrastructure.adapters.codex.transport.assessment.execution import (
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
