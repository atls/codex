"""Shared stdio transport for existing Codex app-server consumers."""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from typing import Any, Self

from model_fit.infrastructure.adapters.codex.transport.rpc_error import (
    AppServerRPCError,
)


class AppServerConnection:
    def __init__(
        self,
        process: subprocess.Popen[bytes],
        client_info: dict[str, str],
        *,
        timeout_message: str = "app-server timed out",
        closed_message: str = "app-server closed stdout",
        initialize_timeout: int = 10,
        close_timeout: int = 3,
    ) -> None:
        self.process = process
        self.pending = b""
        self.next_id = 0
        self.events: list[dict[str, Any]] = []
        self.timeout_message = timeout_message
        self.closed_message = closed_message
        self.close_timeout = close_timeout
        try:
            self.call(
                "initialize",
                {"clientInfo": client_info, "capabilities": {"experimentalApi": True}},
                initialize_timeout,
            )
            self.send({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=self.close_timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=self.close_timeout)
        finally:
            for stream in (
                self.process.stdin,
                self.process.stdout,
                self.process.stderr,
            ):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

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
                raise TimeoutError(self.timeout_message)
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError(self.closed_message)
            self.pending += chunk
        line, self.pending = self.pending.split(b"\n", 1)
        message: object = json.loads(line)
        if not isinstance(message, dict):
            raise ValueError("App-server message must be an object")
        return message

    def call(
        self, method: str, params: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self.send({"method": method, "id": request_id, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            event = self.read(deadline)
            if event.get("id") == request_id:
                if "error" in event:
                    error = event["error"]
                    if not isinstance(error, dict) or not isinstance(
                        error.get("message"), str
                    ):
                        raise ValueError("Malformed app-server error")
                    raise AppServerRPCError(
                        error["message"],
                        method=method,
                        code=error.get("code"),
                        thread_id=params.get("threadId"),
                    )
                result = event["result"]
                if not isinstance(result, dict):
                    raise ValueError("App-server result must be an object")
                return result
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
