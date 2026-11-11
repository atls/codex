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

    def clear(self) -> None:
        self.path.unlink()

    def unsafe(self) -> bool:
        return self.path.is_symlink()
