from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AcceptedInput:
    message_id: str
    client_message_id: str | None
    content: list[dict[str, Any]]
    source_content: list[dict[str, Any]]
