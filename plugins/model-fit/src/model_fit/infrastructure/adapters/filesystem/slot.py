from model_fit.application.switch.types.state import ProcessSnapshot
from pathlib import Path

import model_fit.infrastructure.adapters.filesystem.state as state


class FileSlot:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ProcessSnapshot | None:
        return state.read_state(self.path)

    def save(self, value: ProcessSnapshot) -> None:
        state.write_state(self.path, value)

    def clear(self) -> None:
        self.path.unlink()

    def unsafe(self) -> bool:
        return self.path.is_symlink()
