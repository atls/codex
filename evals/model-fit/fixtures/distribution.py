import shutil
import subprocess
from pathlib import Path

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
    for name in ("README.md", "LICENSE", "pyproject.toml", "uv.lock", "plugin.json"):
        shutil.copyfile(source / name, destination / name)


def archive(source: Path, name: str) -> Path:
    packaging = Path(".github/packaging")
    inventory = packaging / (
        "marketplace.files" if name == "vector-prime" else "directory/files"
    )
    destination = source / "dist" / (name + ".zip")
    destination.parent.mkdir(exist_ok=True)
    manifest = ["plugin.json"] if name == "vector-prime-guidance" else []
    subprocess.run(
        [
            "git",
            "archive",
            "--format=zip",
            f"--output={destination}",
            f"--prefix={name}/",
            "HEAD",
            "--",
            *manifest,
            *(source / inventory).read_text().splitlines(),
        ],
        cwd=source,
        check=True,
        capture_output=True,
        timeout=30,
    )
    return destination
