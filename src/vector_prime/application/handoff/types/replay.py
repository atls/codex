from dataclasses import dataclass

from vector_prime.application.handoff.types.progress import TransferInputEvidence


@dataclass(frozen=True)
class ReplayBound:
    requested_speed: str | None = None
    observed_speed: str | None = None

    @property
    def speed_warning(self) -> str | None:
        if self.requested_speed is None or self.observed_speed == self.requested_speed:
            return None
        return f"Model Fit: the input arrived; requested speed {self.requested_speed}, observed speed {self.observed_speed or 'unknown'}. Continue this input on the current profile."


@dataclass(frozen=True)
class OwnerProfileChanged:
    same_source: bool


@dataclass(frozen=True)
class InputChanged:
    same_source: bool


@dataclass(frozen=True)
class BoundReplay:
    turn_id: str


@dataclass(frozen=True)
class UnboundReplay:
    source_turn_id: str
    earliest_start: int
    input_evidence: TransferInputEvidence
