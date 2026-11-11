import os
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = Path(".github/workflows/package.yml")


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
    job = yaml.safe_load((source / WORKFLOW).read_text())["jobs"]["package"]
    variant = next(
        row for row in job["strategy"]["matrix"]["include"] if row["name"] == name
    )
    env = {
        **os.environ,
        "PACKAGE_NAME": name,
        "PACKAGE_FILES": variant["inventory"],
        "PACKAGE_MANIFEST": variant.get("manifest", ""),
    }
    for step in job["steps"]:
        if "run" not in step or ("if" in step and not env["PACKAGE_MANIFEST"]):
            continue
        subprocess.run(
            ["bash", "-ec", step["run"]],
            cwd=source / step.get("working-directory", "."),
            env=env,
            check=True,
            capture_output=True,
            timeout=30,
        )
    return source / "dist" / (name + ".zip")
