from vector_prime.application.switch.helpers.transfer import is_bound_replay
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
    if not is_bound_replay(state, event.turn_id):
        return False
    return actions.matches_transfer(event)
