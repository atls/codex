from vector_prime.application.switch.helpers.transfer import transfer_instruction
from vector_prime.application.handoff.types.instruction import TransferInstruction
from vector_prime.application.handoff.types.preparation import TransferPreparation
from vector_prime.application.handoff.types.state import TransferState
from vector_prime.infrastructure.adapters.filesystem.handoff import (
    staged_snapshot,
    transfer_state,
)
from vector_prime.application.assessment.helpers.generation import retained_generation
from vector_prime.application.switch.types.state import ProcessSnapshot
from pathlib import Path

import vector_prime.infrastructure.adapters.filesystem.state as state


class FileSlot:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ProcessSnapshot | None:
        return state.read_snapshot(self.path)

    def save(self, value: ProcessSnapshot) -> None:
        state.write_snapshot(self.path, value)

    def save_transition(self, value: ProcessSnapshot) -> ProcessSnapshot:
        current = self.load()
        generation = retained_generation(
            value.get("pending_assessment"),
            current.get("pending_assessment") if current is not None else None,
            current.get("assessment_generation") if current is not None else None,
        )
        if generation is not None:
            value = {**value, "assessment_generation": generation}
        self.save(value)
        return value

    def transfer_state(self) -> TransferState | None:
        return transfer_state(self.load())

    def stage_transfer(self, preparation: TransferPreparation) -> TransferInstruction:
        return transfer_instruction(self.save_transition(staged_snapshot(preparation)))

    def authorize_transfer(self, now: float) -> None:
        self.save_transition({**self._snapshot(), "transfer_authorized_at": now})

    def write_control_turn(self, turn_id: str, continuations: tuple[str, ...]) -> None:
        current = self._snapshot()
        current["control_turn_id"] = turn_id
        if continuations:
            current["continuation_turn_ids"] = list(continuations)
        self.save_transition(current)

    def write_replay_turn(self, turn_id: str) -> None:
        current = self._snapshot()
        current.pop("pending_assessment", None)
        current["replay_turn_id"] = turn_id
        self.save_transition(current)

    def release_transfer(self) -> None:
        current = self.load()
        pending = current.get("pending_assessment") if current is not None else None
        if not pending:
            self.clear()
            return
        if pending.turn_id is None:
            raise ValueError("Pending assessment has no source turn")
        self.save_transition(
            {
                "phase": "submitted",
                "source_turn_id": pending.turn_id,
                "pending_assessment": pending,
            },
        )

    def _snapshot(self) -> ProcessSnapshot:
        current = self.load()
        if current is None:
            raise RuntimeError("Missing handoff snapshot")
        return current

    def clear(self) -> None:
        self.path.unlink()

    def unsafe(self) -> bool:
        return self.path.is_symlink()
