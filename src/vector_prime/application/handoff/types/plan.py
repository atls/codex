from dataclasses import dataclass


@dataclass(frozen=True)
class TransferTarget:
    model: str
    effort: str
    speed: str | None = None

    def matches_quality(self, model: str, effort: str) -> bool:
        return self.model == model and self.effort == effort


@dataclass(frozen=True)
class ManualHandoff:
    reason_code: str
    explanation: str = ""
    retain_profile_context: bool = True
