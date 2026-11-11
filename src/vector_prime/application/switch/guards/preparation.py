from vector_prime.application.handoff.types.state import ReadyTransfer
from vector_prime.application.handoff.types.instruction import TransferInstruction
from vector_prime.application.switch.types.state import ProcessSnapshot


def preparation_is_current(
    current: ProcessSnapshot | None, expected: TransferInstruction
) -> bool:
    transfer = current.get("transfer") if current is not None else None
    instruction = transfer.instruction if isinstance(transfer, ReadyTransfer) else None
    return instruction is not None and (
        instruction.generation,
        instruction.source_turn_id,
        instruction.target,
        instruction.prompt_digest,
    ) == (
        expected.generation,
        expected.source_turn_id,
        expected.target,
        expected.prompt_digest,
    )
