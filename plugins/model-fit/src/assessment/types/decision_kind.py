from typing import Literal, TypeAlias

DecisionKind: TypeAlias = Literal[
    "keep", "unknown", "recommend_lighter", "recommend_stronger", "recommend_faster"
]
