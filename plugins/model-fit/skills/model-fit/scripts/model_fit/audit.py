"""Write private, whitelisted Model Fit diagnostics."""

from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from model_fit.identity import SESSION_ID_PATTERN


def audit_path(session_id: str) -> Path:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("Invalid session id")
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / ".tmp/model-fit-hook-audit" / f"{session_id}.jsonl"


def append_audit(
    session_id: str, turn_id: Any, outcome: str, details: dict[str, Any] | None = None
) -> None:
    path = audit_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    entry = {
        "time": int(time.time()),
        "time_ns": time.time_ns(),
        "pid": os.getpid(),
        "turn_id": turn_id if isinstance(turn_id, str) else None,
        "outcome": outcome,
    }
    if details is not None:
        entry["details"] = {
            key: value
            for key, value in details.items()
            if key in AUDIT_DETAIL_TYPES and type(value) is AUDIT_DETAIL_TYPES[key]
        }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(json.dumps(entry, ensure_ascii=False) + "\n")


def record_audit(
    session_id: str, turn_id: Any, outcome: str, details: dict[str, Any] | None = None
) -> bool:
    try:
        append_audit(session_id, turn_id, outcome, details)
    except (OSError, ValueError) as error:
        print(f"Model Fit audit write failed ({type(error).__name__})", file=sys.stderr)
        return False
    return True


AUDIT_DETAIL_TYPES = {
    "hook_event": str,
    "reason_code": str,
    "state_phase": str,
    "holder_pid": int,
    "holder_operation": str,
    "holder_turn_id": str,
    "holder_acquired_at_ns": int,
    "holder_observed": bool,
    "failure_file": str,
    "failure_function": str,
    "failure_line": int,
}
