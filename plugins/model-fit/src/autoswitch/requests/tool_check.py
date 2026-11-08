from dataclasses import dataclass


@dataclass(frozen=True)
class ToolCheck:
    thread_id: str
    turn_id: str | None
    source: object
