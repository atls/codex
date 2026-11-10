from dataclasses import dataclass
from typing import Literal

from model_fit.application.handoff.types.plan import TransferTarget


@dataclass(frozen=True)
class PreparedHandoff:
    source_turn_id: str
    target: TransferTarget
    created_at: int
    authorized_at: float
    prompt: str
    prompt_digest: str


@dataclass(frozen=True)
class TransferInputEvidence:
    kind: Literal["native_input", "legacy_prompt"]
    digest: str


@dataclass(frozen=True)
class AttemptedHandoff:
    source_turn_id: str
    target: TransferTarget
    client_message_id: str
    input_evidence: TransferInputEvidence
    submission_id: str | None


@dataclass(frozen=True)
class AcceptedHandoff:
    source_turn_id: str
    target: TransferTarget
    submission_id: str
    input_evidence: TransferInputEvidence


@dataclass(frozen=True)
class QueuedHandoff(AcceptedHandoff):
    replay_turn_id: str | None
