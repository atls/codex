from vector_prime.application.assessment.types.profile import ActiveProfile
from vector_prime.application.assessment.types.user_choice import RetainedProfileChoice


def is_retained_choice_consistent(
    choice: RetainedProfileChoice, active: ActiveProfile
) -> bool:
    return choice["profile"] == active
