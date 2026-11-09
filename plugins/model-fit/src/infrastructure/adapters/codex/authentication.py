"""Private credential copy lifecycle for production evaluator subprocesses."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def authenticated_home(
    prefix: str, source_home: Path | None = None
) -> tempfile.TemporaryDirectory:
    temporary = tempfile.TemporaryDirectory(prefix=prefix)
    try:
        source = (
            source_home or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        ) / "auth.json"
        if not source.is_file():
            raise RuntimeError("Existing Codex login is unavailable")
        destination = Path(temporary.name) / "auth.json"
        shutil.copyfile(source, destination)
        destination.chmod(384)
        return temporary
    except Exception:
        temporary.cleanup()
        raise
