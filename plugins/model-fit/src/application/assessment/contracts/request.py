from typing import Any, NotRequired, TypedDict

from model_fit.application.assessment.contracts.profile import Profile
from model_fit.application.assessment.contracts.user_choice import UserChoice


class AssessmentRequest(TypedDict):
    input: NotRequired[list[dict[str, Any]]]
    task: NotRequired[str]
    active_profile: Profile
    context: NotRequired[str | None]
    prior_choice: NotRequired[UserChoice | None]
