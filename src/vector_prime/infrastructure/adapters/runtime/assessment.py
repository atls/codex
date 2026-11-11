"""Run and verify the local Vector Prime CLI subprocess."""

import json
import re
import subprocess
import sys

from vector_prime.application.assessment.decoding import decode_decision
from vector_prime.application.assessment.decision import RECOMMENDATIONS
from vector_prime.application.assessment.exceptions.source_unavailable import (
    SourceUnavailable,
)
from vector_prime.application.assessment.exceptions.unknown_speed_change import (
    UnknownSpeedChange,
)
from vector_prime.application.assessment.types.decision import AssessmentDecision
from vector_prime.application.assessment.types.request import ProfileAssessmentInput


def triage(request: ProfileAssessmentInput) -> AssessmentDecision:
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "vector_prime.entrypoints.cli.assess",
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
