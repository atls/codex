from contextlib import AbstractContextManager
from typing import Protocol

from vector_prime.application.handoff.types.progress import (
    AttemptedHandoff,
    AcceptedHandoff,
)
from vector_prime.application.handoff.types.queue import (
    PreparedQueue,
    QueueConfirmation,
)


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
