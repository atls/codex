from dataclasses import dataclass

from model_fit.application.assessment.types.profile import ActiveProfile
from model_fit.application.submission.types.json import JsonValue


@dataclass(frozen=True)
class NativeProfileObservation:
    profile: ActiveProfile
    current_turn: bool


@dataclass(frozen=True)
class PriorClarification:
    text: str


@dataclass(frozen=True)
class UnfinishedRequest:
    prompt: str
    content: list[dict[str, JsonValue]] | None
    replaces_current: bool


@dataclass(frozen=True)
class ContextAugmentation:
    choice: NativeProfileObservation | PriorClarification | None
    unfinished: UnfinishedRequest | None
