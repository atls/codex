from dataclasses import dataclass


@dataclass(frozen=True)
class HandoffSource:
    turn_id: str
    expected_prompt: str | None
    continuation_turn_ids: tuple[str, ...]
