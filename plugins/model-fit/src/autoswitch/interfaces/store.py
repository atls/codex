from contextlib import AbstractContextManager
from typing import Any, Protocol

from model_fit.autoswitch.interfaces.state import TransferStateSlot


class TransferStateStore(Protocol):
    def transaction(
        self, thread_id: str, **options: Any
    ) -> AbstractContextManager[TransferStateSlot]: ...

    def snapshot(self, thread_id: str) -> dict[str, Any] | None: ...

    def owner(self, thread_id: str) -> dict[str, Any]: ...
