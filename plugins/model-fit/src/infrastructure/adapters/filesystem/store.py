from contextlib import contextmanager

import model_fit.infrastructure.adapters.filesystem.state as state
from model_fit.infrastructure.adapters.filesystem.slot import FileSlot


class FileStore:
    @contextmanager
    def transaction(self, thread_id, **options):
        with state.locked_state(thread_id, **options) as path:
            yield FileSlot(path)

    def snapshot(self, thread_id):
        return state.read_state(state.state_path(thread_id))

    def owner(self, thread_id):
        return state.lock_owner(thread_id)
