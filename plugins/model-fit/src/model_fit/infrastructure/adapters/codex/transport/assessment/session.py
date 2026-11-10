"""Own the isolated Codex process, skill installation and private auth copy."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from model_fit.infrastructure.adapters.codex.authentication import authenticated_home
from model_fit.application.assessment.exceptions.source_unavailable import (
    SourceUnavailable,
)
from model_fit.infrastructure.adapters.codex.transport.connection import (
    AppServerConnection,
)

SKILL = Path(__file__).resolve().parents[7] / "skills/model-fit"


class AppServer(AppServerConnection):
    def __init__(
        self,
        directory: Path,
        skill_dir: Path | None = None,
        stderr_path: Path | None = None,
        codex_path: str = "codex",
    ) -> None:
        if skill_dir is None:
            skill_dir = SKILL
            if not (skill_dir / "references/assessment-policy.md").is_file():
                raise SourceUnavailable("Model Fit assessment policy")
        if not (skill_dir / "SKILL.md").is_file():
            raise SourceUnavailable("Model Fit skill")
        self.home = authenticated_home("model-fit-preflight-home-")
        installed = Path(self.home.name) / "skills/model-fit"
        installed.parent.mkdir(parents=True)
        try:
            shutil.copytree(
                skill_dir,
                installed,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", ".venv", "build", "dist", "*.egg-info"
                ),
            )
        except Exception:
            self.home.cleanup()
            raise
        self.skill_file = installed / "SKILL.md"
        environment = {
            key: value
            for key in ("PATH", "HOME", "SHELL", "TMPDIR", "LANG", "LC_ALL", "USER")
            if (value := os.environ.get(key)) is not None
        }
        environment["CODEX_HOME"] = self.home.name
        self.stderr = stderr_path.open("w") if stderr_path is not None else None
        try:
            self.process = subprocess.Popen(
                [
                    codex_path,
                    "app-server",
                    "--listen",
                    "stdio://",
                    "-c",
                    "features.hooks=false",
                    "-c",
                    "features.plugins=false",
                    "-c",
                    "features.apps=false",
                    "-c",
                    "features.shell_snapshot=false",
                ],
                cwd=directory,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.stderr or subprocess.DEVNULL,
                env=environment,
            )
        except Exception:
            if self.stderr:
                self.stderr.close()
            self.home.cleanup()
            raise
        try:
            super().__init__(
                self.process,
                {
                    "name": "model_fit_preflight",
                    "title": "Model Fit Preflight",
                    "version": "0.1.0",
                },
            )
        except Exception:
            if self.stderr:
                self.stderr.close()
            self.home.cleanup()
            raise

    def close(self) -> None:
        try:
            super().close()
        finally:
            if self.stderr:
                self.stderr.close()
            self.home.cleanup()
