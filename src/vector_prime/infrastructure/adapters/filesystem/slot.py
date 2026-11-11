from vector_prime.application.handoff.types.instruction import TransferInstruction
from vector_prime.application.handoff.types.preparation import TransferPreparation
from vector_prime.application.handoff.types.state import TransferState
from vector_prime.infrastructure.adapters.filesystem.handoff import (
    staged_snapshot,
    read_instruction,
    transfer_state,
)
from vector_prime.application.assessment.helpers.generation import retained_generation
from vector_prime.application.switch.types.state import ProcessSnapshot
from vector_prime.infrastructure.adapters.filesystem.record import FileRecord
from pathlib import Path

import vector_prime.infrastructure.adapters.filesystem.state as state


class FileSlot:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ProcessSnapshot | None:
        return state.read_snapshot(self.path)

    def save(self, value: ProcessSnapshot) -> None:
        state.write_record(
            self.path, state.coordinator_record(value, self.load_record())
        )

    def save_transition(self, value: ProcessSnapshot) -> ProcessSnapshot:
        current = self.load_record()
        generation = retained_generation(
            value.get("pending_assessment"),
            current.get("pending_assessment") if current is not None else None,
            current.get("assessment_generation") if current is not None else None,
        )
        if generation is not None:
            value = {**value, "assessment_generation": generation}
        state.write_record(self.path, state.coordinator_record(value, current))
        return value

    def transfer_state(self) -> TransferState | None:
        return transfer_state(self.load_record())

    def stage_transfer(self, preparation: TransferPreparation) -> TransferInstruction:
        instruction = read_instruction(
            self.save_record_transition(staged_snapshot(preparation))
        )
        assert instruction is not None
        return instruction

    def authorize_transfer(self, now: float) -> None:
        self.save_record_transition({**self._record(), "transfer_authorized_at": now})

    def write_control_turn(self, turn_id: str, continuations: tuple[str, ...]) -> None:
        current = self._record()
        current["control_turn_id"] = turn_id
        if continuations:
            current["continuation_turn_ids"] = list(continuations)
        self.save_record_transition(current)

    def write_replay_turn(self, turn_id: str) -> None:
        current = self._record()
        current.pop("pending_assessment", None)
        current["replay_turn_id"] = turn_id
        self.save_record_transition(current)

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

    def load_record(self) -> FileRecord | None:
        return state.read_record(self.path)

    def save_record_transition(self, value: FileRecord) -> FileRecord:
        current = self.load_record()
        generation = retained_generation(
            value.get("pending_assessment"),
            current.get("pending_assessment") if current is not None else None,
            current.get("assessment_generation") if current is not None else None,
        )
        if generation is not None:
            value = {**value, "assessment_generation": generation}
        state.write_record(self.path, value)
        return value

    def _record(self) -> FileRecord:
        current = self.load_record()
        if current is None:
            raise RuntimeError("Missing handoff snapshot")
        return current

    def clear(self) -> None:
        self.path.unlink()

    def unsafe(self) -> bool:
        return self.path.is_symlink()
