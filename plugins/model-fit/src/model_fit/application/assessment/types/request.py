from model_fit.application.submission.types.json import JsonValue
from typing import NotRequired, TypedDict

from model_fit.application.assessment.types.profile import ActiveProfile
from model_fit.application.assessment.types.user_choice import RetainedProfileChoice


class ProfileAssessmentInput(TypedDict):
    input: NotRequired[list[dict[str, JsonValue]]]
    task: NotRequired[str]
    active_profile: ActiveProfile
    context: NotRequired[str | None]
    prior_choice: NotRequired[RetainedProfileChoice | None]
