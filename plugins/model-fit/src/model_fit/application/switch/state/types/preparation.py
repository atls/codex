from typing import NotRequired, TypedDict


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
