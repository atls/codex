from typing import Any, NotRequired, TypedDict

from model_fit.assessment.types.profile import ActiveProfile
from model_fit.assessment.types.user_choice import RetainedProfileChoice


class ProfileAssessmentInput(TypedDict):
    input: NotRequired[list[dict[str, Any]]]
    task: NotRequired[str]
    active_profile: ActiveProfile
    context: NotRequired[str | None]
    prior_choice: NotRequired[RetainedProfileChoice | None]
