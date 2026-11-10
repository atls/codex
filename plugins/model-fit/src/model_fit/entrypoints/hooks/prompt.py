"""Opt-in Desktop hook that runs Model Fit triage before a user turn."""

from __future__ import annotations
from model_fit.entrypoints.hooks.types.output import HookOutput

from pathlib import Path
from collections.abc import Callable
from model_fit.application.assessment.types.request import ProfileAssessmentInput
import json
import os
import subprocess
import sys

from model_fit.application.switch.handlers.prompt import decide as decide_prompt
from model_fit.entrypoints.hooks.presentation import render_disposition
from model_fit.infrastructure.adapters.codex.assessment import triage
from model_fit.application.submission.helpers.content import (
    prompt_digest as prompt_hash,
)
from model_fit.infrastructure.adapters.codex.history import session_input
from model_fit.infrastructure.adapters.codex.identity import executor_thread_id
from model_fit.infrastructure.adapters.filesystem.audit import record_audit
from model_fit.infrastructure.adapters.filesystem.assessment_cache import (
    FileAssessmentCache,
)
from model_fit.infrastructure.adapters.filesystem.assessment_cache import pending_path

PILOT_THREAD_ENV = "MODEL_FIT_PILOT_THREAD"


def decide(
    request: ProfileAssessmentInput,
    path: Path,
    observe: Callable[[str], bool | None] | None = None,
) -> HookOutput | None:
    result = decide_prompt(
        request,
        thread_id=path.stem,
        recommendations=FileAssessmentCache(lambda thread_id: path),
        assessor=triage,
        digest=prompt_hash,
        observe=observe,
    )
    return render_disposition(result)


def handle_prompt() -> int:
    pilot_thread = os.environ.get(PILOT_THREAD_ENV)
    turn_id = None
    try:
        event = json.load(sys.stdin)
        if (
            not isinstance(event, dict)
            or event.get("hook_event_name") != "UserPromptSubmit"
        ):
            return 0
        if not pilot_thread or executor_thread_id(event) != pilot_thread:
            return 0
        turn_id = event.get("turn_id")
        record_audit(pilot_thread, turn_id, "started")
        output = decide(
            session_input(event),
            pending_path(pilot_thread),
            lambda outcome: record_audit(pilot_thread, turn_id, outcome),
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        TimeoutError,
        subprocess.SubprocessError,
    ) as error:
        output = {
            "systemMessage": "Model Fit: the hook received no validated decision; the profile was not assessed."
        }
        if pilot_thread:
            record_audit(pilot_thread, turn_id, f"error:{type(error).__name__}")
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0
