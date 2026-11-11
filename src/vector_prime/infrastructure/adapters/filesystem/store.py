from collections.abc import Iterator
from vector_prime.application.submission.types.json import JsonValue
from vector_prime.application.switch.types.state import ProcessSnapshot
from contextlib import contextmanager

import vector_prime.infrastructure.adapters.filesystem.state as state
from vector_prime.infrastructure.adapters.filesystem.slot import FileSlot


class FileStore:
    @contextmanager
    def transaction(
        self,
        thread_id: str,
        *,
        nonblocking: bool = False,
        operation: str = "unknown",
        turn_id: str | None = None,
    ) -> Iterator[FileSlot]:
        with state.locked_state(
            thread_id, nonblocking=nonblocking, operation=operation, turn_id=turn_id
        ) as path:
            yield FileSlot(path)

    def snapshot(self, thread_id: str) -> ProcessSnapshot | None:
        return state.read_state(state.state_path(thread_id))

    def owner(self, thread_id: str) -> dict[str, JsonValue]:
        return state.lock_owner(thread_id)
