from typing import Literal, TypeAlias
from typing_extensions import TypedDict
from pydantic import ConfigDict, with_config

DecisionKind: TypeAlias = Literal[
    "keep", "recommend_lighter", "recommend_stronger", "recommend_faster", "unknown"
]


@with_config(ConfigDict(extra="forbid"))
class AssessmentDecision(TypedDict):
    active_model: str
    active_effort: str
    active_speed: str | None
    decision: DecisionKind
    recommended_model: str | None
    recommended_effort: str | None
    recommended_speed: str | None
    official_source_url: str | None
    official_guidance: str | None
    task_inference: str | None
    reason: str
