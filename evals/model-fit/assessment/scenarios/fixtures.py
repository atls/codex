import shutil
import subprocess
from pathlib import Path

SUITE = Path(__file__).resolve().parents[2]


def fixture_context(case):
    if not case.get("fixture_directory"):
        return None
    relative = Path(case["fixture_directory"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Fixture path escapes eval directory")
    source = SUITE / relative
    if not source.resolve().is_relative_to(SUITE.resolve()) or any(
        (
            (SUITE / Path(*relative.parts[:index])).is_symlink()
            for index in range(1, len(relative.parts) + 1)
        )
    ):
        raise ValueError("Fixture path escapes or contains a symlink")
    if (
        not source.is_dir()
        or source.is_symlink()
        or any((path.is_symlink() for path in source.rglob("*")))
    ):
        raise ValueError("Fixture directory is missing or contains a symlink")
    context = "\n".join(
        (
            f"<{p.relative_to(source)}>\n{p.read_text()}\n</{p.relative_to(source)}>"
            for p in sorted(source.rglob("*.md"))
        )
    )
    if len(context) > 20000:
        raise ValueError("Fixture context exceeds the preflight limit")
    return context


def prepare_workspace(root, identifier, case=None):
    if (
        not isinstance(identifier, str)
        or not identifier
        or Path(identifier).name != identifier
        or (identifier in {".", ".."})
    ):
        raise ValueError("Invalid workspace identity")
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Disposable workspace root is unavailable")
    workspace = root / identifier
    if workspace.is_symlink():
        raise ValueError("Workspace cannot be a symlink")
    if workspace.exists():
        if not (workspace / ".git").is_dir():
            raise ValueError("Existing workspace is not the prepared repository")
        return str(workspace)
    if case and case.get("fixture_directory"):
        fixture_context(case)
    workspace.mkdir(mode=448)
    if case and case.get("fixture_directory"):
        relative = Path(case.get("fixture_target", ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Fixture target escapes workspace")
        shutil.copytree(
            SUITE / case["fixture_directory"], workspace / relative, dirs_exist_ok=True
        )
    subprocess.run(
        ["git", "init", "-q", str(workspace)], check=True, capture_output=True
    )
    return str(workspace)
