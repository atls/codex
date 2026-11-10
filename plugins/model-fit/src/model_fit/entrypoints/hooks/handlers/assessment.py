from __future__ import annotations
import json
import os
import subprocess
from model_fit.application.switch.exceptions.unavailable import SubmissionUnavailable
from model_fit.entrypoints.hooks.activation import (
    automatic_allowed,
)
from model_fit.entrypoints.hooks.instructions import (
    admission_unavailable_context,
    inactive_context,
)
from model_fit.entrypoints.hooks.operations import (
    assess_submitted,
    reassess,
)
from model_fit.infrastructure.adapters.filesystem.audit import (
    failure_location,
    record_audit,
)


def assess_current(
    *, check_admission: bool = False, requirements: str | None = None
) -> int:
    try:
        output = assess_submitted() if requirements is None else reassess(requirements)
    except SubmissionUnavailable as error:
        if error.thread_id:
            record_audit(
                error.thread_id,
                None,
                "auto_assessment_error:SubmissionUnavailable",
                {
                    "hook_event": "assessment",
                    "reason_code": error.reason_code,
                    **failure_location(error),
                },
            )
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": "SubmissionUnavailable",
                    "reason_code": error.reason_code,
                }
            )
        )
        return 1
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        TimeoutError,
        subprocess.SubprocessError,
    ) as error:
        thread = os.environ.get("CODEX_THREAD_ID")
        if thread:
            record_audit(
                thread,
                None,
                f"auto_assessment_error:{type(error).__name__}",
                {
                    "hook_event": "assessment",
                    "reason_code": "assessment_failed",
                    **failure_location(error),
                },
            )
        print(json.dumps({"status": "failed", "error": type(error).__name__}))
        return 1
    admitted = (
        automatic_allowed("UserPromptSubmit", os.getcwd()) if check_admission else True
    )
    if admitted is not True:
        thread = os.environ.get("CODEX_THREAD_ID")
        if thread:
            record_audit(
                thread,
                None,
                "auto_assessment_revoked"
                if admitted is False
                else "auto_assessment_admission_unknown",
                {
                    "hook_event": "assessment",
                    "reason_code": "automatic_admission_revoked"
                    if admitted is False
                    else "automatic_admission_unavailable",
                },
            )
        output = (
            inactive_context() if admitted is False else admission_unavailable_context()
        )
    print(json.dumps(output, ensure_ascii=False))
    return 1 if output.get("decision") == "block" else 0
