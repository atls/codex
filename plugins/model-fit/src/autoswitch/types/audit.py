from typing import Protocol
from model_fit.native_input.types.json import JsonValue


class AuditWriter(Protocol):
    def __call__(
        self,
        thread_id: str,
        turn_id: str | None,
        outcome: str,
        details: dict[str, JsonValue] | None = None,
        /,
        *,
        error: BaseException | None = None,
    ) -> bool | None: ...
