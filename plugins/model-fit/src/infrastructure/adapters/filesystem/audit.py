"""Append privacy-filtered lifecycle observations without changing hook results."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from model_fit.native_input.types.json import JsonValue

from model_fit.infrastructure.adapters.codex.identity import SESSION_ID_PATTERN

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
    "triage_decision": str,
    "active_model": str,
    "active_effort": str,
    "recommended_model": str,
    "recommended_effort": str,
    "task_sha256": str,
    "context_sha256": str,
    "root_session_id": str,
    "agent_id": str,
    "input_sha256": str,
    "assessment_generation": str,
}


def audit_path(session_id: str) -> Path:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("Invalid session id")
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / ".tmp/model-fit-hook-audit" / f"{session_id}.jsonl"


def append_audit(
    session_id: str,
    turn_id: object,
    outcome: str,
    details: dict[str, JsonValue] | None = None,
) -> None:
    path = audit_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=448)
    entry: dict[str, JsonValue] = {
        "time": int(time.time()),
        "time_ns": time.time_ns(),
        "pid": os.getpid(),
        "executor_thread_id": session_id,
        "turn_id": turn_id if isinstance(turn_id, str) else None,
        "outcome": outcome,
    }
    if details is not None:
        entry["details"] = {
            key: value
            for key, value in details.items()
            if key in AUDIT_DETAIL_TYPES and type(value) is AUDIT_DETAIL_TYPES[key]
        }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 384)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(json.dumps(entry, ensure_ascii=False) + "\n")


def failure_location(error: BaseException) -> dict[str, JsonValue]:
    frames = traceback.extract_tb(error.__traceback__)
    if not frames:
        return {}
    frame = frames[-1]
    return {
        "failure_file": Path(frame.filename).name,
        "failure_function": frame.name,
        "failure_line": frame.lineno,
    }


def record_audit(
    session_id: str,
    turn_id: object,
    outcome: str,
    details: dict[str, JsonValue] | None = None,
    *,
    error: BaseException | None = None,
) -> bool:
    if error is not None:
        details = {**(details or {}), **failure_location(error)}
    try:
        append_audit(session_id, turn_id, outcome, details)
    except (OSError, ValueError) as error:
        print(f"Model Fit audit write failed ({type(error).__name__})", file=sys.stderr)
        return False
    return True
