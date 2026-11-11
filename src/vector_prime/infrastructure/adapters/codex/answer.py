"""Conservative answer relevance check against accepted native input."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from importlib.resources import files

from vector_prime.infrastructure.adapters.codex.authentication import authenticated_home

SCHEMA = files("vector_prime.application.answer").joinpath("relevance.schema.json")
EVALUATOR_MODEL = "gpt-6-luna"
EVALUATOR_EFFORT = "low"
EVALUATOR_TIMEOUT_SECONDS = 20


def evaluate_relevance(prompt: str) -> object:
    with (
        tempfile.TemporaryDirectory(prefix="model-fit-replay-answer-") as scratch_name,
        authenticated_home("model-fit-replay-auth-") as home_name,
    ):
        scratch = Path(scratch_name)
        isolated = Path(home_name)
        output = scratch / "answer.json"
        command = [
            "codex",
            "exec",
            "--ignore-user-config",
            "--disable",
            "hooks",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
            "-C",
            str(scratch),
            "-m",
            EVALUATOR_MODEL,
            "-c",
            f"model_reasoning_effort={EVALUATOR_EFFORT}",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(SCHEMA),
            "--output-last-message",
            str(output),
            "-",
        ]
        result = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=EVALUATOR_TIMEOUT_SECONDS,
            env={**os.environ, "CODEX_HOME": str(isolated)},
        )
        if result.returncode != 0 or not output.is_file():
            raise RuntimeError("Replay answer evaluation did not complete")
        for line in result.stdout.splitlines():
            event = json.loads(line)
            if event.get("type") == "item.started" and event.get("item", {}).get(
                "type"
            ) not in {"user_message", "agent_message", "reasoning"}:
                raise RuntimeError("Replay answer evaluation attempted a tool")
        return json.loads(output.read_text())
