from vector_prime.application.assessment.types.state import PendingAssessment


def retained_generation(
    pending: PendingAssessment | None,
    previous: PendingAssessment | None,
    previous_generation: str | int | None,
) -> str | int | None:
    generation = pending.generation if pending is not None else None
    if generation is not None:
        return generation
    if previous is not None and previous.generation is not None:
        return previous.generation
    return previous_generation
