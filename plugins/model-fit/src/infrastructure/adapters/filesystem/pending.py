import json
import os
import tempfile
from pathlib import Path
from typing import Any

from model_fit.assessment.validation import RECOMMENDATIONS
from model_fit.infrastructure.adapters.codex.codec import prompt_digest as prompt_hash
from model_fit.infrastructure.adapters.codex.identity import SESSION_ID_PATTERN


def pending_path(session_id: str) -> Path:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("Invalid session id")
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / ".tmp/model-fit-hook-pending" / f"{session_id}.json"


def load_pending(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    pending = json.loads(path.read_text())
    if not isinstance(pending, dict) or set(pending) != {
        "prompt_hash",
        "active_profile",
        "result",
    }:
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
    return pending


def save_pending(path: Path, request: dict[str, Any], result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=448)
    data = {
        "prompt_hash": prompt_hash(request["task"]),
        "active_profile": request["active_profile"],
        "result": result,
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
