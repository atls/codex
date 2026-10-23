"""Read Codex app-server messages over an isolated stdio connection."""

from __future__ import annotations
import json
import os
import select
import subprocess
import time
from typing import Any


class AppServerRPCError(RuntimeError):
    pass


class AppServerReader:
    def __init__(self, cwd: str) -> None:
        self.process = subprocess.Popen(
            [
                "codex",
                "app-server",
                "--listen",
                "stdio://",
                "-c",
                "features.hooks=false",
            ],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.pending = b""
        self.next_id = 0
        try:
            self.call(
                "initialize",
                {
                    "clientInfo": {
                        "name": "model_fit_hook",
                        "title": "Model Fit Hook",
                        "version": "0.1",
                    },
                    "capabilities": {"experimentalApi": True},
                },
                10,
            )
            self.send({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise

    def __enter__(self) -> AppServerReader:
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
            self.process.wait(timeout=3)

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        self.process.stdin.flush()

    def read(self, deadline: float) -> dict[str, Any]:
        assert self.process.stdout is not None
        while b"\n" not in self.pending:
            remaining = deadline - time.monotonic()
            if (
                remaining <= 0
                or not select.select([self.process.stdout], [], [], remaining)[0]
            ):
                raise TimeoutError("app-server profile read timed out")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("app-server closed before profile read")
            self.pending += chunk
        line, self.pending = self.pending.split(b"\n", 1)
        return json.loads(line)

    def call(self, method: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            response = self.read(deadline)
            if response.get("id") == request_id:
                if "error" in response:
                    raise AppServerRPCError(
                        f"{method}: {response['error'].get('message')}"
                    )
                return response["result"]
            if "id" in response and "method" in response:
                raise RuntimeError(
                    f"Unexpected app-server request: {response['method']}"
                )
