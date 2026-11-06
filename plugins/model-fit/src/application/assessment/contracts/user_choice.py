from typing import Literal, TypedDict

from model_fit.application.assessment.contracts.profile import Profile


class UserChoice(TypedDict):
    user_selected: Literal[True]
    same_work: Literal[True]
    profile: Profile
