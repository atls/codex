"""File-backed Model Fit handoff state and per-thread lock ownership."""

from __future__ import annotations

import fcntl
import json
import hashlib
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
from typing_extensions import TypedDict
from vector_prime.application.switch.types.state import ProcessSnapshot
from vector_prime.infrastructure.adapters.filesystem.record import FileRecord, Snapshot
from vector_prime.infrastructure.adapters.filesystem.handoff import transfer_state
from vector_prime.application.assessment.types.state import (
    PendingAssessment,
    Waiting,
    Running,
    Failed,
    Unrecognized,
)
from vector_prime.application.submission.decoding import checked_object
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


class LegacyAssessmentRecord(TypedDict, total=False):
    thread_id: str
    turn_id: str
    root_session_id: str
    agent_id: str | None
    working_directory: str | None
    active_model: str | None
    prompt_hash: str
    empty_text: bool
    status: str
    generation: str | int
    failure_reason: str


LegacySnapshot = Snapshot[LegacyAssessmentRecord]
LEGACY_STATE = TypeAdapter(LegacySnapshot)
RECORD_STATE = TypeAdapter(FileRecord)
RUNTIME_STATE = TypeAdapter(ProcessSnapshot)
COORDINATION_FIELDS = ProcessSnapshot.__annotations__.keys() - {"transfer", "revision"}


def decode_record(stored: LegacySnapshot) -> FileRecord:
    payload: dict[str, object] = dict(stored)
    pending = stored.get("pending_assessment")
    if pending is not None:
        status, reason = pending.get("status"), pending.get("failure_reason")
        progress: Waiting | Running | Failed | Unrecognized
        if status == "waiting":
            progress = Waiting(reason)
        elif status == "running":
            progress = Running(reason)
        elif status == "failed":
            progress = Failed(reason)
        else:
            progress = Unrecognized(status, reason)
        payload["pending_assessment"] = PendingAssessment(
            progress=progress,
            thread_id=pending.get("thread_id"),
            turn_id=pending.get("turn_id"),
            root_session_id=pending.get("root_session_id"),
            agent_id=pending.get("agent_id"),
            working_directory=pending.get("working_directory"),
            active_model=pending.get("active_model"),
            prompt_hash=pending.get("prompt_hash"),
            empty_text=pending.get("empty_text"),
            generation=pending.get("generation"),
            stored_fields=frozenset(pending) - {"status", "failure_reason"},
            additional_fields=checked_object(
                {
                    key: value
                    for key, value in pending.items()
                    if key not in LegacyAssessmentRecord.__annotations__
                }
            ),
        )
    return RECORD_STATE.validate_python(payload, strict=True, extra="allow")


def read_record(path: Path) -> FileRecord | None:
    stored = read_state(path)
    return decode_record(stored) if stored is not None else None


def read_snapshot(path: Path) -> ProcessSnapshot | None:
    stored = read_state(path)
    if stored is None:
        return None
    record = decode_record(stored)
    projection = {
        key: value for key, value in record.items() if key in COORDINATION_FIELDS
    }
    projection["transfer"] = transfer_state(record)
    projection["revision"] = hashlib.sha256(
        json.dumps(stored, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return RUNTIME_STATE.validate_python(projection, strict=True)


def coordinator_record(
    snapshot: ProcessSnapshot, current: FileRecord | None
) -> FileRecord:
    payload = {
        key: value for key, value in snapshot.items() if key in COORDINATION_FIELDS
    }
    if (
        current is not None
        and "revision" in snapshot
        and current["phase"] == snapshot["phase"]
    ):
        payload = {
            **{
                key: value
                for key, value in current.items()
                if key not in COORDINATION_FIELDS
            },
            **payload,
        }
    return RECORD_STATE.validate_python(payload, strict=True, extra="allow")


def write_record(path: Path, snapshot: FileRecord) -> None:
    payload: dict[str, object] = dict(snapshot)
    pending = snapshot.get("pending_assessment")
    if pending is not None:
        values: dict[str, JsonValue] = {
            "thread_id": pending.thread_id,
            "turn_id": pending.turn_id,
            "root_session_id": pending.root_session_id,
            "agent_id": pending.agent_id,
            "working_directory": pending.working_directory,
            "active_model": pending.active_model,
            "prompt_hash": pending.prompt_hash,
            "empty_text": pending.empty_text,
            "generation": pending.generation,
        }
        record = {
            **pending.additional_fields,
            **{key: values[key] for key in pending.stored_fields if key in values},
        }
        if pending.status is not None:
            record["status"] = pending.status
        if pending.failure_reason is not None:
            record["failure_reason"] = pending.failure_reason
        payload["pending_assessment"] = record
    write_state(path, decode_state(payload))


def decode_state(value: object) -> LegacySnapshot:
    try:
        return LEGACY_STATE.validate_python(value, strict=True, extra="allow")
    except ValidationError:
        raise ValueError("Invalid Model Fit handoff state") from None


def read_state(path: Path) -> LegacySnapshot | None:
    if not path.exists():
        return None
    return decode_state(json.loads(path.read_text()))


def write_state(path: Path, state: LegacySnapshot) -> None:
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
