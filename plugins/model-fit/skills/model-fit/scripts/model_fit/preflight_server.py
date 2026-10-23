"""Run an isolated Codex app-server preflight with the installed skill."""

from __future__ import annotations
import json
import os
import select
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from model_fit.preflight import SKILL


class AppServer:
    def __init__(
        self, directory: Path, skill_dir: Path = SKILL, stderr_path: Path | None = None
    ) -> None:
        self.home = tempfile.TemporaryDirectory(prefix="model-fit-preflight-home-")
        auth = (
            Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "auth.json"
        )
        if not auth.is_file():
            self.home.cleanup()
            raise RuntimeError("Existing Codex login is unavailable")
        (Path(self.home.name) / "auth.json").symlink_to(auth)
        installed = Path(self.home.name) / "skills/model-fit"
        installed.parent.mkdir(parents=True)
        try:
            shutil.copytree(
                skill_dir,
                installed,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
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
                    "codex",
                    "app-server",
                    "--listen",
                    "stdio://",
                    "-c",
                    "features.hooks=false",
                    "-c",
                    "features.plugins=false",
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
        self.pending = b""
        self.next_id = 0
        self.events: list[dict[str, Any]] = []
        try:
            self.call(
                "initialize",
                {
                    "clientInfo": {
                        "name": "model_fit_preflight",
                        "title": "Model Fit Preflight",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
                10,
            )
            self.send({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise

    def __enter__(self) -> AppServer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
        if self.stderr:
            self.stderr.close()
        self.home.cleanup()

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        self.process.stdin.flush()

    def read(self, deadline: float) -> dict[str, Any]:
        assert self.process.stdout is not None
        while b"\n" not in self.pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("app-server timed out")
            ready, _, _ = select.select([self.process.stdout], [], [], remaining)
            if not ready:
                raise TimeoutError("app-server timed out")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("app-server closed stdout")
            self.pending += chunk
        line, self.pending = self.pending.split(b"\n", 1)
        return json.loads(line)

    def call(self, method: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self.send({"method": method, "id": request_id, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            event = self.read(deadline)
            if event.get("id") == request_id:
                if "error" in event:
                    raise RuntimeError(f"{method}: {event['error'].get('message')}")
                return event["result"]
            if "id" in event and "method" in event:
                raise RuntimeError(f"Unexpected app-server request: {event['method']}")
            self.events.append(event)

    def wait_turn(self, thread_id: str, turn_id: str, timeout: int) -> str:
        deadline = time.monotonic() + timeout
        offset = 0
        while True:
            while offset < len(self.events):
                event = self.events[offset]
                offset += 1
                if event.get("method") == "turn/completed":
                    params = event.get("params") or {}
                    turn = params.get("turn") or {}
                    if (
                        params.get("threadId") == thread_id
                        and turn.get("id") == turn_id
                    ):
                        return str(turn.get("status"))
            self.events.append(self.read(deadline))
