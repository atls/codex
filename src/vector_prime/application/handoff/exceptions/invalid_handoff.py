from typing import Literal


class InvalidHandoff(ValueError):
    def __init__(
        self,
        reason: Literal[
            "foreign_executor",
            "not_prepared",
            "expired",
            "profile_not_applied",
            "invalid_state",
        ],
    ) -> None:
        messages = {
            "foreign_executor": "Queue helper must run in the target Desktop thread",
            "not_prepared": "No matching Model Fit handoff",
            "expired": "Model Fit handoff expired",
            "profile_not_applied": "Target profile was not applied to the next turn",
            "invalid_state": "Model Fit handoff lacks validated phase evidence",
        }
        super().__init__(messages[reason])
        self.reason = reason
