from model_fit.autoswitch.state.types.record import HandoffStateRecord
from pathlib import Path

import model_fit.infrastructure.adapters.filesystem.state as state


class FileSlot:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> HandoffStateRecord | None:
        return state.read_state(self.path)

    def save(self, value: HandoffStateRecord) -> None:
        state.write_state(self.path, value)

    def clear(self) -> None:
        self.path.unlink()

    def unsafe(self) -> bool:
        return self.path.is_symlink()
