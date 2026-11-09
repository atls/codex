from typing import Literal, TypedDict

from model_fit.assessment.profile import ActiveProfile


class RetainedProfileChoice(TypedDict):
    user_selected: Literal[True]
    same_work: Literal[True]
    profile: ActiveProfile
