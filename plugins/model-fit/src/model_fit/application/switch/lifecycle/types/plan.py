from dataclasses import dataclass


@dataclass(frozen=True)
class TransferTarget:
    model: str
    effort: str


@dataclass(frozen=True)
class ManualHandoff:
    reason_code: str
    explanation: str = ""
    retain_profile_context: bool = True
