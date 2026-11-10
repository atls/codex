import json
import os
import tempfile
from pathlib import Path
from model_fit.assessment.types.request import ProfileAssessmentInput
from model_fit.assessment.types.decision import AssessmentDecision
from model_fit.autoswitch.recommendation.types.record import RecommendationRecord
from model_fit.assessment.validation import validated_active_profile
from model_fit.autoswitch.recommendation.decoding import decode_evidence
from model_fit.autoswitch.recommendation.identity import assessment_hash

from model_fit.assessment.validation import RECOMMENDATIONS
from model_fit.native_input.codec import prompt_digest as prompt_hash
from model_fit.infrastructure.adapters.codex.identity import SESSION_ID_PATTERN


def pending_path(session_id: str) -> Path:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("Invalid session id")
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / ".tmp/model-fit-hook-pending" / f"{session_id}.json"


def load_pending(path: Path) -> RecommendationRecord | None:
    if not path.exists():
        return None
    pending = json.loads(path.read_text())
    required = {"prompt_hash", "active_profile", "result"}
    if (
        not isinstance(pending, dict)
        or not required.issubset(pending)
        or not set(pending).issubset(required | {"assessment_hash"})
    ):
        raise ValueError("Invalid pending recommendation")
    if not isinstance(pending["prompt_hash"], str) or not isinstance(
        pending["active_profile"], dict
    ):
        raise ValueError("Invalid pending recommendation")
    if (
        not isinstance(pending["result"], dict)
        or pending["result"].get("decision") not in RECOMMENDATIONS
    ):
        raise ValueError("Invalid pending recommendation")
    record: RecommendationRecord = {
        "prompt_hash": pending["prompt_hash"],
        "active_profile": validated_active_profile(
            {"active_profile": pending["active_profile"]}
        ),
        "result": decode_evidence(pending["result"]),
    }
    if "assessment_hash" in pending:
        fingerprint = pending["assessment_hash"]
        if not isinstance(fingerprint, str):
            raise ValueError("Invalid assessment input hash")
        record["assessment_hash"] = fingerprint
    return record


def save_pending(
    path: Path, request: ProfileAssessmentInput, result: AssessmentDecision
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=448)
    data = {
        "prompt_hash": prompt_hash(request["task"]),
        "active_profile": request["active_profile"],
        "result": result,
        "assessment_hash": assessment_hash(request),
    }
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temporary_path = Path(output.name)
            json.dump(data, output, ensure_ascii=False)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
