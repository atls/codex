from vector_prime.application.assessment.types.state import PendingAssessmentRecord


def retained_generation(
    pending: PendingAssessmentRecord | None,
    previous: PendingAssessmentRecord | None,
    previous_generation: str | int | None,
) -> str | int | None:
    generation = pending.get("generation") if pending is not None else None
    if generation is not None:
        return generation
    if previous is not None:
        return previous.get("generation", previous_generation)
    return previous_generation
