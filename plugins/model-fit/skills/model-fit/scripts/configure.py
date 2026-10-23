"""Configure native project hooks for one explicitly selected Codex thread."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from model_fit.identity import SESSION_ID_PATTERN


EVENT_TIMEOUTS = {"UserPromptSubmit": 360, "PreToolUse": 10, "Stop": 45}


def hook_command(thread_id: str) -> str:
    if not SESSION_ID_PATTERN.fullmatch(thread_id):
        raise ValueError("Invalid Codex thread ID")
    script = Path(__file__).resolve().with_name("hook.py")
    return (
        f"MODEL_FIT_AUTO_THREAD={thread_id} /usr/bin/python3 {shlex.quote(str(script))}"
    )


def load_hooks(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("Project hooks file is a symlink")
    if not path.exists():
        return {"description": "Project-local Model Fit", "hooks": {}}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not isinstance(value.get("hooks"), dict):
        raise ValueError("Invalid project hooks file")
    return value


def configure(
    data: dict[str, Any], thread_id: str, remove: bool = False
) -> dict[str, Any]:
    command = hook_command(thread_id)
    marker = f"MODEL_FIT_AUTO_THREAD={thread_id} "
    updated = json.loads(json.dumps(data))
    hooks = updated["hooks"]
    for event, timeout in EVENT_TIMEOUTS.items():
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"Invalid {event} hook groups")
        found = False
        retained = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError(f"Invalid {event} hook group")
            handlers = []
            for handler in group["hooks"]:
                if not isinstance(handler, dict):
                    raise ValueError(f"Invalid {event} hook handler")
                configured = handler.get("command")
                if isinstance(configured, str) and marker in configured:
                    if (
                        handler.get("type") != "command"
                        or configured != command
                        or handler.get("timeout") != timeout
                    ):
                        raise ValueError(
                            "Conflicting Model Fit hook for the selected thread"
                        )
                    found = True
                    if remove:
                        continue
                handlers.append(handler)
            if handlers:
                retained.append({**group, "hooks": handlers})
        if not remove and not found:
            retained.append(
                {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
            )
        hooks[event] = retained
    return updated


def save(path: Path, data: dict[str, Any]) -> None:
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("Project hook location is a symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def ensure_local_exclude(project: Path) -> None:
    project = project.resolve()
    root = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if root.returncode != 0:
        return
    if Path(root.stdout.strip()).resolve() != project:
        raise ValueError("Project must be the Git repository root")
    tracked = subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "ls-files",
            "--error-unmatch",
            "--",
            ".codex/hooks.json",
        ],
        capture_output=True,
    )
    if tracked.returncode == 0:
        raise ValueError("Project hooks file is tracked by Git")
    location = subprocess.check_output(
        ["git", "-C", str(project), "rev-parse", "--git-path", "info/exclude"],
        text=True,
    ).strip()
    exclude = Path(location)
    if not exclude.is_absolute():
        exclude = project / exclude
    existing = exclude.read_text() if exclude.exists() else ""
    if "/.codex/hooks.json" not in existing.splitlines():
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as output:
            output.write(
                ("\n" if existing and not existing.endswith("\n") else "")
                + "/.codex/hooks.json\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    project = args.project.resolve()
    if not project.is_dir():
        parser.error("Project directory does not exist")
    path = project / ".codex/hooks.json"
    result = configure(load_hooks(path), args.thread_id, args.remove)
    if args.write:
        ensure_local_exclude(project)
        save(path, result)
        if load_hooks(path) != result:
            raise RuntimeError("Project hook readback does not match")
    print(
        json.dumps(
            {
                "path": str(path),
                "action": "removed" if args.remove else "configured",
                "written": args.write,
                "events": list(EVENT_TIMEOUTS),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
