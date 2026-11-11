from dataclasses import dataclass, field
from typing import ClassVar

from vector_prime.application.submission.types.json import JsonValue


@dataclass(frozen=True)
class Waiting:
    status: ClassVar[str] = "waiting"
    failure_reason: str | None = None


@dataclass(frozen=True)
class Running:
    status: ClassVar[str] = "running"
    failure_reason: str | None = None


@dataclass(frozen=True)
class Failed:
    status: ClassVar[str] = "failed"
    failure_reason: str | None = None


@dataclass(frozen=True)
class Unrecognized:
    status: str | None
    failure_reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class PendingAssessment:
    progress: Waiting | Running | Failed | Unrecognized
    thread_id: str | None = None
    turn_id: str | None = None
    root_session_id: str | None = None
    agent_id: str | None = None
    working_directory: str | None = None
    active_model: str | None = None
    prompt_hash: str | None = None
    empty_text: bool | None = None
    generation: str | int | None = None
    stored_fields: frozenset[str] = frozenset()
    additional_fields: dict[str, JsonValue] = field(default_factory=dict)

    @property
    def status(self) -> str | None:
        return self.progress.status

    @property
    def failure_reason(self) -> str | None:
        return self.progress.failure_reason

    def __bool__(self) -> bool:
        return bool(
            self.stored_fields
            or self.status is not None
            or self.failure_reason is not None
        )
