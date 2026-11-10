from collections.abc import Callable
import json
import os
import tempfile
from pathlib import Path
from model_fit.application.assessment.types.request import ProfileAssessmentInput
from model_fit.application.assessment.types.decision import AssessmentDecision
from model_fit.application.assessment.types.recommendation import (
    RecommendationRecord,
)
from pydantic import TypeAdapter, ValidationError
from model_fit.application.assessment.helpers.identity import assessment_hash

from model_fit.application.assessment.constraints.decision import RECOMMENDATIONS
from model_fit.application.submission.helpers.content import (
    prompt_digest as prompt_hash,
)
from model_fit.infrastructure.adapters.codex.identity import SESSION_ID_PATTERN


CACHE_RECORD = TypeAdapter(RecommendationRecord)


def pending_path(session_id: str) -> Path:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("Invalid session id")
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / ".tmp/model-fit-hook-pending" / f"{session_id}.json"


def load_pending(path: Path) -> RecommendationRecord | None:
    if not path.exists():
        return None
    try:
        record = CACHE_RECORD.validate_python(json.loads(path.read_text()), strict=True)
    except ValidationError:
        raise ValueError("Invalid pending recommendation") from None
    if record["result"]["decision"] not in RECOMMENDATIONS:
        raise ValueError("Invalid pending recommendation")
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


class FileAssessmentCache:
    def __init__(self, path_for_thread: Callable[[str], Path] = pending_path) -> None:
        self.path_for_thread = path_for_thread

    def load(self, thread_id: str) -> RecommendationRecord | None:
        path = self.path_for_thread(thread_id)
        if path.is_symlink():
            raise ValueError("Blocking recommendation cannot be a symlink")
        return load_pending(path)

    def save(
        self,
        thread_id: str,
        request: ProfileAssessmentInput,
        result: AssessmentDecision,
    ) -> None:
        save_pending(self.path_for_thread(thread_id), request, result)

    def clear(self, thread_id: str, *, missing_ok: bool = False) -> None:
        self.path_for_thread(thread_id).unlink(missing_ok=missing_ok)
