from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Receipt:
    submission_id: str
    accepted_input: list[dict[str, Any]]
