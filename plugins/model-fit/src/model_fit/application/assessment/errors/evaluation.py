from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationError:
    exception_type: str
