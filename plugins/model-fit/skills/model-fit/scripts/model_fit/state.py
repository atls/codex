"""Private state and lock ownership for one Model Fit thread."""

from __future__ import annotations
import fcntl
import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from model_fit.identity import SESSION_ID_PATTERN

STATE_DIRECTORY = ".tmp/model-fit-auto-switch"


def state_path(thread_id: str) -> Path:
    if not SESSION_ID_PATTERN.fullmatch(thread_id):
        raise ValueError("Invalid thread id")
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / STATE_DIRECTORY / f"{thread_id}.json"


@contextmanager
def locked_state(
    thread_id: str,
    nonblocking: bool = False,
    operation: str = "unknown",
    turn_id: str | None = None,
) -> Iterator[Path]:
    path = state_path(thread_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "r+") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ValueError("Invalid Model Fit state lock")
        fcntl.flock(lock, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        safe_turn_id = (
            turn_id
            if isinstance(turn_id, str) and SESSION_ID_PATTERN.fullmatch(turn_id)
            else None
        )
        owner = {
            "pid": os.getpid(),
            "operation": operation,
            "turn_id": safe_turn_id,
            "acquired_at_ns": time.time_ns(),
        }
        lock.seek(0)
        lock.truncate()
        lock.write(json.dumps(owner))
        lock.flush()
        try:
            yield path
        finally:
            lock.seek(0)
            lock.truncate()
            lock.flush()


def lock_owner(thread_id: str) -> dict[str, Any]:
    try:
        owner = json.loads(state_path(thread_id).with_suffix(".lock").read_text())
    except (OSError, ValueError):
        return {"holder_observed": False}
    if not isinstance(owner, dict) or type(owner.get("pid")) is not int:
        return {"holder_observed": False}
    details: dict[str, Any] = {"holder_observed": True, "holder_pid": owner["pid"]}
    if isinstance(owner.get("operation"), str) and owner["operation"] in {
        "prompt_submit",
        "pre_tool_use",
        "queue",
        "stop",
        "unknown",
    }:
        details["holder_operation"] = owner["operation"]
    if isinstance(owner.get("turn_id"), str) and SESSION_ID_PATTERN.fullmatch(
        owner["turn_id"]
    ):
        details["holder_turn_id"] = owner["turn_id"]
    if type(owner.get("acquired_at_ns")) is int:
        details["holder_acquired_at_ns"] = owner["acquired_at_ns"]
    return details


def read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    state = json.loads(path.read_text())
    if not isinstance(state, dict) or state.get("phase") not in {
        "ready",
        "attempting",
        "queued",
        "rejected",
        "passed",
    }:
        raise ValueError("Invalid Model Fit handoff state")
    return state


def write_state(path: Path, state: dict[str, Any]) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            json.dump(state, output, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
