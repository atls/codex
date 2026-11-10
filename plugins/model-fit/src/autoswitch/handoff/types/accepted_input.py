from model_fit.native_input.types.json import JsonValue
from dataclasses import dataclass


@dataclass(frozen=True)
class AcceptedNativeInput:
    message_id: str
    client_message_id: str | None
    content: list[dict[str, JsonValue]]
    source_content: list[dict[str, JsonValue]]
