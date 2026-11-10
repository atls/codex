from typing import Literal, TypedDict

from model_fit.application.assessment.types.profile import ActiveProfile


class RetainedProfileChoice(TypedDict):
    user_selected: Literal[True]
    same_work: Literal[True]
    profile: ActiveProfile
