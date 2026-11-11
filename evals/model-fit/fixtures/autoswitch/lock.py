import json
import select
import subprocess
import sys
from contextlib import contextmanager

from fixtures.process import native_process

HOLD = """
import sys
from vector_prime.infrastructure.adapters.filesystem.state import locked_state

with locked_state(sys.argv[1], operation=sys.argv[2], turn_id=sys.argv[3] or None):
    print("locked", flush=True)
    sys.stdin.readline()
"""

WRITE = """
import json
import sys
from vector_prime.infrastructure.adapters.filesystem.state import locked_state, write_state

with locked_state(sys.argv[1]) as path:
    write_state(path, json.loads(sys.argv[2]))
"""


@contextmanager
def held_lock(thread_id, *, operation="unknown", turn_id=None):
    with native_process(
        [sys.executable, "-c", HOLD, thread_id, operation, turn_id or ""],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        if not select.select([process.stdout], [], [], 3)[0]:
            raise AssertionError("Fixture process did not acquire the state lock")
        if process.stdout.readline().strip() != "locked":
            raise AssertionError(
                "Fixture process exited before acquiring the state lock"
            )
        yield process.pid


def write_concurrent_state(thread_id, state):
    subprocess.run(
        [sys.executable, "-c", WRITE, thread_id, json.dumps(state)],
        check=True,
        capture_output=True,
        timeout=3,
    )
