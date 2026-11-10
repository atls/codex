from typing import Literal


class HandoffConflict(RuntimeError):
    def __init__(
        self, reason: Literal["pending_assessment", "rejected", "outcome_unknown"]
    ) -> None:
        messages = {
            "pending_assessment": "New native input must be assessed before queueing",
            "rejected": "Queue rejected this handoff; send a new prompt",
            "outcome_unknown": "Previous queue attempt has an unknown outcome; do not retry",
        }
        super().__init__(messages[reason])
        self.reason = reason
