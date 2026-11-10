from typing import Protocol
from model_fit.native_input.types.json import JsonValue
from contextlib import AbstractContextManager
from model_fit.autoswitch.state.types.record import HandoffStateRecord


class TransferStateSlot(Protocol):
    def load(self) -> HandoffStateRecord | None: ...

    def save(self, value: HandoffStateRecord) -> None: ...

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

    def snapshot(self, thread_id: str) -> HandoffStateRecord | None: ...

    def owner(self, thread_id: str) -> dict[str, JsonValue]: ...
