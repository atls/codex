from typing import Protocol

from vector_prime.application.handoff.types.instruction import TransferInstruction
from vector_prime.application.handoff.types.preparation import TransferPreparation
from vector_prime.application.handoff.types.state import TransferState


class HandoffSlot(Protocol):
    def transfer_state(self) -> TransferState | None: ...

    def stage_transfer(
        self, preparation: TransferPreparation
    ) -> TransferInstruction: ...

    def authorize_transfer(self, now: float) -> None: ...

    def write_control_turn(
        self, turn_id: str, continuations: tuple[str, ...]
    ) -> None: ...

    def write_replay_turn(self, turn_id: str) -> None: ...

    def release_transfer(self) -> None: ...
