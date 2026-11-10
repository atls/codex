from model_fit.application.switch.types.state import ProcessSnapshot
from model_fit.application.submission.types.json import JsonValue
from contextlib import AbstractContextManager
from typing import Protocol
from model_fit.application.handoff.types.accepted_input import (
    AcceptedNativeInput,
)
from model_fit.application.handoff.types.queue_receipt import NativeQueueReceipt
from model_fit.application.handoff.errors.queue_rejection import NativeQueueRejection
from model_fit.application.handoff.types.source import HandoffSource


class NativeConversation(Protocol):
    def parent_thread_id(self, thread_id: str) -> str | None: ...

    def latest_turn_id(self, thread_id: str) -> str | None: ...

    def accepted_input(self, thread_id: str, turn_id: str) -> AcceptedNativeInput: ...

    def profile(self, thread_id: str) -> tuple[str | None, str | None]: ...

    def enqueue(
        self, thread_id: str, turn_id: str, content: list[dict[str, JsonValue]]
    ) -> NativeQueueReceipt | NativeQueueRejection: ...

    def delete(self, thread_id: str, submission_id: str) -> bool: ...

    def replay_input(
        self, thread_id: str, turn_id: str
    ) -> list[dict[str, JsonValue]] | None: ...

    def queued_ids(self, thread_id: str) -> set[str]: ...

    def source_input(
        self, thread_id: str, turn_id: str, *, include_steering: bool = False
    ) -> list[dict[str, JsonValue]]: ...

    def handoff_input(
        self, thread_id: str, source: HandoffSource
    ) -> list[dict[str, JsonValue]]: ...

    def replay_finished(self, thread_id: str, state: ProcessSnapshot) -> bool: ...

    def source_terminal_without_replay(
        self, thread_id: str, source_turn_id: str, current_turn_id: str
    ) -> bool: ...

    def unsubmitted_successor(
        self, thread_id: str, source_turn_id: str, current_turn_id: str
    ) -> bool: ...


class NativeConversationFactory(Protocol):
    def __call__(
        self, cwd: str | None, /
    ) -> AbstractContextManager[NativeConversation]: ...
