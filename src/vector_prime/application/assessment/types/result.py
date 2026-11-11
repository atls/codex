from dataclasses import dataclass


@dataclass(frozen=True)
class UnknownAssessment:
    message: str | None = None
