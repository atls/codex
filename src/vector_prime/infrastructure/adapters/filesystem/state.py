"""File-backed Model Fit handoff state and per-thread lock ownership."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from vector_prime.application.submission.types.json import JsonValue

from vector_prime.infrastructure.adapters.filesystem.constraints.is_safe_key import (
    is_safe_key,
)
from vector_prime.application.switch.types.state import ProcessSnapshot
from pydantic import TypeAdapter, ValidationError

STATE_DIRECTORY = ".tmp/model-fit-auto-switch"


def state_path(thread_id: str) -> Path:
    if not is_safe_key(thread_id):
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
    path.parent.mkdir(parents=True, exist_ok=True, mode=448)
    descriptor = os.open(
        path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 384
    )
    with os.fdopen(descriptor, "r+") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ValueError("Invalid Model Fit state lock")
        fcntl.flock(lock, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        safe_turn_id = turn_id if is_safe_key(turn_id) else None
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


def lock_owner(thread_id: str) -> dict[str, JsonValue]:
    try:
        owner = json.loads(state_path(thread_id).with_suffix(".lock").read_text())
    except (OSError, ValueError):
        return {"holder_observed": False}
    if not isinstance(owner, dict) or type(owner.get("pid")) is not int:
        return {"holder_observed": False}
    details: dict[str, JsonValue] = {
        "holder_observed": True,
        "holder_pid": owner["pid"],
    }
    if isinstance(owner.get("operation"), str) and owner["operation"] in {
        "prompt_submit",
        "pre_tool_use",
        "assessment",
        "queue",
        "stop",
        "unknown",
    }:
        details["holder_operation"] = owner["operation"]
    if is_safe_key(owner["turn_id"]):
        details["holder_turn_id"] = owner["turn_id"]
    if type(owner.get("acquired_at_ns")) is int:
        details["holder_acquired_at_ns"] = owner["acquired_at_ns"]
    return details


LEGACY_STATE = TypeAdapter(ProcessSnapshot)


def decode_state(value: object) -> ProcessSnapshot:
    try:
        return LEGACY_STATE.validate_python(value, strict=True, extra="allow")
    except ValidationError:
        raise ValueError("Invalid Model Fit handoff state") from None


def read_state(path: Path) -> ProcessSnapshot | None:
    if not path.exists():
        return None
    return decode_state(json.loads(path.read_text()))


def write_state(path: Path, state: ProcessSnapshot) -> None:
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
