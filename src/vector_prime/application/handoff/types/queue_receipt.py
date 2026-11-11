from vector_prime.application.submission.types.json import JsonValue
from dataclasses import dataclass


@dataclass(frozen=True)
class NativeQueueReceipt:
    submission_id: str
    accepted_input: list[dict[str, JsonValue]] | None
