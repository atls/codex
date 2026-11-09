from typing import Any, Protocol


class AuditWriter(Protocol):
    def __call__(
        self,
        thread_id: str,
        turn_id: str | None,
        outcome: str,
        details: dict[str, Any] | None = None,
        /,
    ) -> None: ...
