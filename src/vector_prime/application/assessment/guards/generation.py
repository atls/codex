from vector_prime.application.assessment.decoding import required_text
from vector_prime.application.assessment.exceptions.superseded import (
    AssessmentSuperseded,
)
from vector_prime.application.assessment.types.state import PendingAssessment


def require_current(
    expected: PendingAssessment, observed: PendingAssessment | None
) -> None:
    if observed != expected:
        raise AssessmentSuperseded(
            required_text(expected.thread_id),
            required_text(expected.turn_id),
            expected.generation,
        )


def generation_known(value: str | int | None) -> bool:
    return type(value) is int or (isinstance(value, str) and bool(value))


def require_generation(
    thread_id: str,
    turn_id: str,
    expected: str | int | None,
    observed: str | int | None,
) -> None:
    if not generation_known(expected) or observed != expected:
        raise AssessmentSuperseded(thread_id, turn_id, expected)
