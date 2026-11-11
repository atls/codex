from vector_prime.application.submission.types.json import JsonValue
from dataclasses import dataclass


@dataclass(frozen=True)
class SubmissionInput:
    thread_id: str
    turn_id: str
    text: str
    working_directory: str | None
    active_model: str | None
    source: dict[str, JsonValue]
    session_id: str | None = None
