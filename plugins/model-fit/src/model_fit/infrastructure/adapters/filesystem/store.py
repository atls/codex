from collections.abc import Iterator
from model_fit.application.submission.types.json import JsonValue
from model_fit.application.switch.types.state import ProcessSnapshot
from contextlib import contextmanager

import model_fit.infrastructure.adapters.filesystem.state as state
from model_fit.infrastructure.adapters.filesystem.slot import FileSlot


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
