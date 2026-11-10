from model_fit.application.submission.types.json import JsonValue
from dataclasses import dataclass


@dataclass(frozen=True)
class ReplayAnswerInput:
    thread_id: str | None
    turn_id: str | None
    answer: str | None
    stop_hook_active: bool | None
    working_directory: str | None
    source: dict[str, JsonValue]
