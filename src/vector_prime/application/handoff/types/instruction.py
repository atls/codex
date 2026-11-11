from dataclasses import dataclass

from vector_prime.application.handoff.types.plan import TransferTarget


@dataclass(frozen=True)
class TransferInstruction:
    source_turn_id: str
    generation: str | int | None
    prompt_digest: str
    target: TransferTarget
    official_source_url: str
    official_guidance: str
    task_inference: str
