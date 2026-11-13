import shutil
import subprocess
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[3]


def copy_source(source: Path, destination: Path) -> None:
    for name in (
        "src",
        "scripts",
        "hooks",
        "assets",
        "skills",
        ".codex-plugin",
        "docs",
    ):
        shutil.copytree(
            source / name,
            destination / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    for name in ("README.md", "LICENSE", "pyproject.toml", "uv.lock"):
        shutil.copyfile(source / name, destination / name)


def archive(source: Path, name: str) -> Path:
    subprocess.run(
        [sys.executable, ".github/packaging/build.py", "--distribution", name],
        cwd=source,
        check=True,
        capture_output=True,
        timeout=30,
    )
    return source / "dist" / (name + ".zip")
