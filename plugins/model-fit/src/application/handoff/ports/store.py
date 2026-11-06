from contextlib import AbstractContextManager
from typing import Any, Protocol

from model_fit.application.handoff.ports.state import State


class Store(Protocol):
    def transaction(
        self, thread_id: str, **options: Any
    ) -> AbstractContextManager[State]: ...
    def snapshot(self, thread_id: str) -> dict[str, Any] | None: ...
    def owner(self, thread_id: str) -> dict[str, Any]: ...
