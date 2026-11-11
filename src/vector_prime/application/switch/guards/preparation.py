from vector_prime.application.handoff.types.instruction import TransferInstruction
from vector_prime.application.switch.types.state import ProcessSnapshot


def preparation_is_current(
    current: ProcessSnapshot | None, expected: TransferInstruction
) -> bool:
    if current is None or current["phase"] != "ready":
        return False
    return all(
        (
            current.get("assessment_generation") == expected.generation,
            current["source_turn_id"] == expected.source_turn_id,
            current.get("target_model") == expected.target.model,
            current.get("target_effort") == expected.target.effort,
            current.get("prompt_digest") == expected.prompt_digest,
        )
    )
