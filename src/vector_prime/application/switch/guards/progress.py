from vector_prime.application.assessment.types.state import PendingAssessmentRecord
from vector_prime.application.switch.types.state import ProcessSnapshot


def require_registration_state(state: ProcessSnapshot | None, *, unsafe: bool) -> None:
    if unsafe or (state is not None and state["phase"] in {"attempting", "rejected"}):
        raise RuntimeError("Cannot replace an unresolved transfer with a submission")


def require_admission_state(state: ProcessSnapshot | None) -> None:
    if state is not None and state["phase"] not in {"ready", "passed", "submitted"}:
        raise RuntimeError("Admission cannot discard an unresolved queue attempt")


def require_consumption(
    state: ProcessSnapshot | None, pending: PendingAssessmentRecord
) -> None:
    if (
        state is None
        or state["phase"] != "queued"
        or state.get("pending_assessment") != pending
    ):
        raise RuntimeError("Native queue receipt changed during assessment")
