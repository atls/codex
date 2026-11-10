from model_fit.application.switch.admission.types.input import ToolAdmissionInput
from model_fit.application.switch.admission.types.tools import TransferTools
from model_fit.application.switch.state.types.record import HandoffStateRecord


def replay_transfer_completed(
    event: ToolAdmissionInput,
    state: HandoffStateRecord | None,
    *,
    actions: TransferTools,
) -> bool:
    if state is None or state["phase"] != "queued":
        return False
    if state.get("replay_turn_id") != event.turn_id:
        return False
    return actions.matches_transfer(event)
