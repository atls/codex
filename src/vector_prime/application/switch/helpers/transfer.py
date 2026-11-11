from vector_prime.application.handoff.exceptions.invalid_handoff import InvalidHandoff
from vector_prime.application.handoff.types.instruction import TransferInstruction
from vector_prime.application.handoff.types.state import QueuedTransfer, ReadyTransfer
from vector_prime.application.switch.types.state import ProcessSnapshot


def transfer_instruction(state: ProcessSnapshot) -> TransferInstruction:
    transfer = state.get("transfer")
    if not isinstance(transfer, ReadyTransfer) or transfer.instruction is None:
        raise InvalidHandoff("invalid_state")
    return transfer.instruction


def is_control_turn(state: ProcessSnapshot, turn_id: str | None) -> bool:
    transfer = state.get("transfer")
    return turn_id == state["source_turn_id"] or (
        transfer is not None and turn_id == transfer.control_turn_id
    )


def is_bound_replay(state: ProcessSnapshot, turn_id: str | None) -> bool:
    transfer = state.get("transfer")
    return isinstance(transfer, QueuedTransfer) and transfer.replay_turn_id == turn_id
