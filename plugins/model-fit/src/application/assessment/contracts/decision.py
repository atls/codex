from typing import Literal, TypedDict


class Decision(TypedDict):
    active_model: str
    active_effort: str
    active_speed: str | None
    decision: Literal[
        "keep", "unknown", "recommend_lighter", "recommend_stronger", "recommend_faster"
    ]
    recommended_model: str | None
    recommended_effort: str | None
    recommended_speed: str | None
    official_source_url: str | None
    official_guidance: str | None
    task_inference: str | None
    reason: str
