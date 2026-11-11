from dataclasses import dataclass

from vector_prime.application.handoff.types.plan import TransferTarget
from vector_prime.application.handoff.types.preparation import TransferContinuation
from vector_prime.application.handoff.types.progress import (
    PreparedHandoff,
    TransferInputEvidence,
)


@dataclass(frozen=True)
class ReadyTransfer:
    source_turn_id: str
    pending_assessment: bool
    continuation: TransferContinuation | None
    prepared: PreparedHandoff | None
    continuation_turn_ids: tuple[str, ...]


@dataclass(frozen=True)
class QueuedTransfer:
    source_turn_id: str
    submission_id: str | None
    client_message_id: str | None
    replay_turn_id: str | None
    target: TransferTarget | None
    earliest_start: int | None
    input_evidence: TransferInputEvidence | None
    hook_prompt_digest: str | None
    continuation_turn_ids: tuple[str, ...]


@dataclass(frozen=True)
class RejectedTransfer:
    source_turn_id: str


@dataclass(frozen=True)
class AttemptingTransfer:
    pass


TransferState = ReadyTransfer | QueuedTransfer | RejectedTransfer | AttemptingTransfer
