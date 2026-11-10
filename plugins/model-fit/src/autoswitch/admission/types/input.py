from model_fit.native_input.types.json import JsonValue
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolAdmissionInput:
    thread_id: str
    turn_id: str | None
    source: dict[str, JsonValue]
