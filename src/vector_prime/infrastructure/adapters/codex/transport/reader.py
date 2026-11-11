from __future__ import annotations

import subprocess

from vector_prime.infrastructure.adapters.codex.transport.connection import (
    AppServerConnection,
)


class AppServerReader(AppServerConnection):
    def __init__(self, cwd: str, *, hook_inventory: bool = False) -> None:
        command = ["codex", "app-server", "--listen", "stdio://"]
        if not hook_inventory:
            command.extend(["-c", "features.hooks=false"])
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        super().__init__(
            process,
            {
                "name": "model_fit_desktop_hook",
                "title": "Model Fit Desktop Hook",
                "version": "0.1",
            },
            timeout_message="app-server profile read timed out",
            closed_message="app-server closed before profile read",
            initialize_timeout=2 if hook_inventory else 10,
            close_timeout=1 if hook_inventory else 3,
        )
