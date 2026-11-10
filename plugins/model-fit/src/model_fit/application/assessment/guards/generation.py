from model_fit.application.assessment.exceptions.superseded import AssessmentSuperseded
from model_fit.application.assessment.types.state import PendingAssessmentRecord


def require_current(
    expected: PendingAssessmentRecord, observed: PendingAssessmentRecord | None
) -> None:
    if observed != expected:
        raise AssessmentSuperseded(
            expected["thread_id"], expected["turn_id"], expected.get("generation")
        )


def require_waiting(pending: PendingAssessmentRecord) -> None:
    if pending["status"] != "waiting":
        raise RuntimeError("Submitted Model Fit input is not awaiting assessment")
