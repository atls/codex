from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from vector_prime.application.handoff.types.progress import (
    AcceptedHandoff,
    AttemptedHandoff,
    PreparedHandoff,
)
from vector_prime.application.handoff.types.source import HandoffSource
from vector_prime.application.handoff.types.state import TransferState
from vector_prime.application.submission.types.json import JsonValue


@dataclass(frozen=True)
class QueueConfirmation:
    submission_id: str
    already_confirmed: bool = False


@dataclass(frozen=True)
class PreparedQueue:
    transfer: PreparedHandoff
    source: HandoffSource


@dataclass(frozen=True)
class QueueCandidate:
    source_turn_id: str
    pending_assessment: bool
    transfer: TransferState | None


@dataclass(frozen=True)
class NativeQueueReceipt:
    submission_id: str
    accepted_input: list[dict[str, JsonValue]] | None


class QueueSlot(Protocol):
    def prepare(
        self, turn_id: str, now: float
    ) -> PreparedQueue | QueueConfirmation: ...
    def write_attempt(
        self, attempt: AttemptedHandoff, prompt_digest: str, hook_prompt_digest: str
    ) -> None: ...
    def write_receipt_id(self, submission_id: str) -> None: ...
    def write_accepted_digest(self, digest: str) -> None: ...
    def confirm(self, accepted: AcceptedHandoff, queued_at: int) -> None: ...
    def reject(self) -> None: ...


class QueueStore(Protocol):
    def queue(
        self, thread_id: str, turn_id: str
    ) -> AbstractContextManager[QueueSlot]: ...
