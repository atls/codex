"""Own every process started by an isolated native installation fixture."""

import os
import signal
import subprocess
from contextlib import contextmanager


@contextmanager
def native_process(command, **options):
    with subprocess.Popen(command, start_new_session=True, **options) as process:
        try:
            yield process
        finally:
            # A completed CLI or app-server can leave a marketplace Git fetch alive.
            # This session belongs to this fixture; terminate it before deleting HOME.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
