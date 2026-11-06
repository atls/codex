"""Invoke the profile assessment CLI and verify its response boundary."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Any

from model_fit.application.assessment.validation import RECOMMENDATIONS
from model_fit.application.assessment.failures.source_unavailable import (
    SourceUnavailable,
)


def triage(request: dict[str, Any]) -> dict[str, Any]:
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "model_fit.entrypoints.assessment.cli",
            "--timeout",
            "45",
        ],
        input=json.dumps(request, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=75,
    )
    failures = {
        "SourceUnavailable": SourceUnavailable,
        "TimeoutError": TimeoutError,
        "ValueError": ValueError,
        "KeyError": KeyError,
        "TypeError": TypeError,
        "RuntimeError": RuntimeError,
        "OSError": OSError,
        "CalledProcessError": RuntimeError,
        "TimeoutExpired": TimeoutError,
    }
    diagnostic = re.search(
        r"(?m)^model-fit triage (?:input )?error: ([A-Za-z][A-Za-z0-9_]{0,100})$",
        process.stderr,
    )
    if process.returncode != 0 and diagnostic:
        raise failures.get(diagnostic.group(1), RuntimeError)(
            "Assessment CLI did not return a verified allocation"
        )
    result = json.loads(process.stdout)
    if not isinstance(result, dict) or result.get("decision") not in (
        RECOMMENDATIONS | {"keep", "unknown"}
    ):
        raise ValueError("Triage returned an invalid decision")
    for field in ("model", "effort", "speed"):
        if result.get(f"active_{field}") != request["active_profile"][field]:
            raise ValueError("Triage changed the active profile")
    if process.returncode not in (0, 1) or (process.returncode == 1) != (
        result["decision"] == "unknown"
    ):
        raise ValueError("Triage exit status contradicts its decision")
    return result
