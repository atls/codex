from typing import Any, Protocol

from model_fit.autoswitch.contracts.accepted_input import AcceptedInput
from model_fit.autoswitch.contracts.receipt import Receipt


class Conversation(Protocol):
    def parent_thread_id(self, thread_id: str) -> str | None: ...

    def latest_turn_id(self, thread_id: str) -> str | None: ...

    def accepted_input(self, thread_id: str, turn_id: str) -> AcceptedInput: ...

    def profile(self, thread_id: str) -> tuple[str | None, str | None]: ...

    def enqueue(
        self, thread_id: str, turn_id: str, content: list[dict[str, Any]]
    ) -> Receipt: ...

    def delete(self, thread_id: str, submission_id: str) -> bool: ...

    def replay_input(
        self, thread_id: str, turn_id: str
    ) -> list[dict[str, Any]] | None: ...

    def queued_ids(self, thread_id: str) -> set[str]: ...

    def source_input(
        self, thread_id: str, turn_id: str, **options: Any
    ) -> list[dict[str, Any]]: ...

    def handoff_input(
        self, thread_id: str, state: dict[str, Any]
    ) -> list[dict[str, Any]]: ...

    def replay_finished(self, thread_id: str, state: dict[str, Any]) -> bool: ...

    def source_terminal_without_replay(
        self, thread_id: str, source_turn_id: str, current_turn_id: str
    ) -> bool: ...

    def unsubmitted_successor(
        self, thread_id: str, source_turn_id: str, current_turn_id: str
    ) -> bool: ...
