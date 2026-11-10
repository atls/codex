from dataclasses import dataclass


@dataclass(frozen=True)
class QueueConfirmation:
    submission_id: str
    already_confirmed: bool = False
