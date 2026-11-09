from dataclasses import dataclass


@dataclass(frozen=True)
class SubmissionInput:
    thread_id: str
    turn_id: str
    text: str
    working_directory: object
    active_model: str | None
    source: object
    session_id: str | None = None
