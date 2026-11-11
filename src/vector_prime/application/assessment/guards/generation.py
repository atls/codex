from vector_prime.application.assessment.exceptions.superseded import (
    AssessmentSuperseded,
)
from vector_prime.application.assessment.types.state import PendingAssessmentRecord


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


def generation_known(value: str | int | None) -> bool:
    return type(value) is int or (isinstance(value, str) and bool(value))


def require_generation(
    thread_id: str,
    turn_id: str,
    expected: str | int,
    observed: str | int | None,
) -> None:
    if not generation_known(expected) or observed != expected:
        raise AssessmentSuperseded(thread_id, turn_id, expected)
