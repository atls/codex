from typing import Protocol
from model_fit.application.submission.types.json import JsonValue
from contextlib import AbstractContextManager
from model_fit.application.switch.types.state import ProcessSnapshot


class TransferStateSlot(Protocol):
    def load(self) -> ProcessSnapshot | None: ...

    def save(self, value: ProcessSnapshot) -> None: ...

    def clear(self) -> None: ...

    def unsafe(self) -> bool: ...


class TransferStateStore(Protocol):
    def transaction(
        self,
        thread_id: str,
        *,
        nonblocking: bool = False,
        operation: str = "unknown",
        turn_id: str | None = None,
    ) -> AbstractContextManager[TransferStateSlot]: ...

    def snapshot(self, thread_id: str) -> ProcessSnapshot | None: ...

    def owner(self, thread_id: str) -> dict[str, JsonValue]: ...
