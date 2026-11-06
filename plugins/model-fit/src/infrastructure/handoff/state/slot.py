from pathlib import Path

import model_fit.infrastructure.handoff.state.files as state


class FileSlot:
    def __init__(self, path: Path):
        self.path = path

    def load(self):
        return state.read_state(self.path)

    def save(self, value):
        state.write_state(self.path, value)

    def clear(self):
        self.path.unlink()

    def unsafe(self):
        return self.path.is_symlink()
