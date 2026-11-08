"""Record synthetic native hook events before dispatching the candidate hook."""

import json
import os
import subprocess
import sys
from pathlib import Path

home = Path(os.environ["CODEX_HOME"])
raw = sys.stdin.read()
event = json.loads(raw)
result = subprocess.run(
    [
        "uv",
        "run",
        "--quiet",
        "--project",
        str(Path(__file__).resolve().parents[1]),
        "python",
        str(Path(__file__).with_name("desktop.py")),
        "hook",
    ],
    input=raw,
    capture_output=True,
    text=True,
)
snapshot = home / ".tmp/model-fit-auto-switch" / (event["session_id"] + ".json")
state = json.loads(snapshot.read_text()) if snapshot.is_file() else None
record = {
    "state_snapshot": state,
    "event": event,
    "returncode": result.returncode,
    "stdout": result.stdout,
    "stderr": result.stderr,
}
fd = os.open(
    home / "acceptance-hook-events.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
)
with os.fdopen(fd, "w") as output:
    output.write(json.dumps(record, ensure_ascii=False) + "\n")
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
raise SystemExit(result.returncode)
