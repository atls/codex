from dataclasses import dataclass

from vector_prime.application.handoff.types.progress import TransferInputEvidence


@dataclass(frozen=True)
class ReplayBound:
    pass


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
