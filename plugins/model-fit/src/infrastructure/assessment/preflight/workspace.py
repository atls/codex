import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def assessment_workspace() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="model-fit-preflight-repo-") as name:
        directory = Path(name)
        subprocess.run(["git", "init", "-q", str(directory)], check=True)
        yield directory
