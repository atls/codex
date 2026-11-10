from model_fit.autoswitch.state.types.record import HandoffStateRecord
from model_fit.autoswitch.state.types.storage import TransferStateSlot


def save_snapshot(
    slot: TransferStateSlot, state: HandoffStateRecord
) -> HandoffStateRecord:
    current = slot.load()
    pending = state.get("pending_assessment")
    generation = pending.get("generation") if pending is not None else None
    if generation is None and current is not None:
        current_pending = current.get("pending_assessment")
        generation = (
            current_pending.get("generation", current.get("assessment_generation"))
            if current_pending is not None
            else current.get("assessment_generation")
        )
    if generation is not None:
        state = {**state, "assessment_generation": generation}
    slot.save(state)
    return state
