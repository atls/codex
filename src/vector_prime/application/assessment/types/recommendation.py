from typing import NotRequired
from typing_extensions import TypedDict
from pydantic import ConfigDict, with_config

from vector_prime.application.assessment.types.evidence import (
    RecommendationEvidence,
)
from vector_prime.application.assessment.types.profile import ActiveProfile


@with_config(ConfigDict(extra="forbid"))
class RecommendationRecord(TypedDict):
    prompt_hash: str
    active_profile: ActiveProfile
    result: RecommendationEvidence
    assessment_hash: NotRequired[str]
