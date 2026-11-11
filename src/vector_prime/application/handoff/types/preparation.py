from dataclasses import dataclass
from typing import NotRequired, TypedDict

from vector_prime.application.handoff.types.source import HandoffSource


class TransferPreparation(TypedDict):
    created_at: int
    source_turn_id: str
    prompt: str
    prompt_digest: str
    target_model: str
    target_effort: str
    official_source_url: str | None
    official_guidance: str | None
    task_inference: str | None
    control_turn_id: NotRequired[str]
    continuation_turn_ids: NotRequired[list[str]]


@dataclass(frozen=True)
class TransferContinuation:
    source_turn_id: str
    prompt: str
    prompt_digest: str
    continuation_turn_ids: tuple[str, ...]

    def source(self) -> HandoffSource:
        return HandoffSource(
            self.source_turn_id, self.prompt, self.continuation_turn_ids
        )
