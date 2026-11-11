from vector_prime.application.handoff.types.preparation import TransferContinuation


def reuses_original_input(turn_id: str, transfer: TransferContinuation) -> bool:
    return (
        turn_id == transfer.source_turn_id or turn_id in transfer.continuation_turn_ids
    )
