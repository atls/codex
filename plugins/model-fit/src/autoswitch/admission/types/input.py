from dataclasses import dataclass


@dataclass(frozen=True)
class ToolAdmissionInput:
    thread_id: str
    turn_id: str | None
    source: object
