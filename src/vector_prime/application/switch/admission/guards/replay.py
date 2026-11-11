from vector_prime.application.switch.admission.types.input import ToolAdmissionInput
from vector_prime.application.switch.admission.types.tools import TransferTools
from vector_prime.application.switch.types.state import ProcessSnapshot


def replay_transfer_completed(
    event: ToolAdmissionInput,
    state: ProcessSnapshot | None,
    *,
    actions: TransferTools,
) -> bool:
    if state is None or state["phase"] != "queued":
        return False
    if state.get("replay_turn_id") != event.turn_id:
        return False
    return actions.matches_transfer(event)
