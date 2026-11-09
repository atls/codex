"""Isolated resources held for the lifetime of the official Promptfoo CLI."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path

SUITE = Path(__file__).resolve().parents[3]
REPOSITORY = SUITE.parents[1]
sys.path.insert(0, str(REPOSITORY / "plugins/model-fit/src"))
from model_fit.infrastructure.adapters.codex.authentication import authenticated_home

from infrastructure.adapters.codex.configuration import (
    PROVIDER_ENV,
    provider_configuration,
)


@contextmanager
def evaluation_session(cases, *, install_skill=True, model="gpt-6.1-sol", effort="low"):
    source_home = Path(
        os.environ.get("CODEX_EVAL_HOME")
        or os.environ.get("CODEX_HOME")
        or Path.home() / ".codex"
    )
    if (
        json.loads((source_home / "auth.json").read_text()).get("auth_mode")
        != "chatgpt"
    ):
        raise ValueError("Subscription evals require an existing ChatGPT login")
    executable = str(
        Path(os.environ.get("CODEX_PATH") or shutil.which("codex") or "codex").resolve()
    )
    with ExitStack() as stack:
        root = Path(
            stack.enter_context(tempfile.TemporaryDirectory(prefix="model-fit-evals-"))
        ).resolve()
        home = Path(
            stack.enter_context(authenticated_home("model-fit-eval-auth-", source_home))
        )
        (home / "skills").mkdir()
        skill = home / "skills/model-fit"
        if install_skill:
            shutil.copytree(
                REPOSITORY / "plugins/model-fit/skills/model-fit",
                skill,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", ".venv", "build", "dist", "*.egg-info"
                ),
            )
        tools = home / "bin"
        tools.mkdir()
        shell_path = str(tools) + os.pathsep + os.environ.get("PATH", "")
        workspaces = {}
        for case in cases:
            identifier = case["id"]
            if (
                not isinstance(identifier, str)
                or not identifier
                or Path(identifier).name != identifier
                or (identifier in {".", ".."})
                or (identifier in workspaces)
            ):
                raise ValueError("Workspace IDs must be unique path components")
            workspace = root / identifier
            workspace.mkdir()
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            workspaces[identifier] = str(workspace)
        config, judge = provider_configuration(
            executable, home, shell_path, model, effort
        )
        yield {
            "config": config,
            "judge": judge,
            "providerEnv": PROVIDER_ENV,
            "version": subprocess.check_output(
                [executable, "--version"], text=True
            ).strip(),
            "skill": str(skill / "SKILL.md") if install_skill else None,
            "workspaces": workspaces,
            "executable": executable,
            "root": str(root),
        }
