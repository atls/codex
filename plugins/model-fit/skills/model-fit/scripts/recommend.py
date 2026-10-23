"""Opt-in Desktop hook that runs Model Fit triage before a user turn."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable


from model_fit.audit import record_audit
from model_fit.recommendation import RECOMMENDATIONS, hook_output, session_input, triage
from model_fit.identity import SESSION_ID_PATTERN

PILOT_THREAD_ENV = "MODEL_FIT_PILOT_THREAD"


def pending_path(session_id: str) -> Path:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("Invalid session id")
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / ".tmp/model-fit-hook-pending" / f"{session_id}.json"


def prompt_hash(prompt: str) -> str:
    return sha256(prompt.encode()).hexdigest()


def load_pending(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    pending = json.loads(path.read_text())
    if not isinstance(pending, dict) or set(pending) != {
        "prompt_hash",
        "active_profile",
        "result",
    }:
        raise ValueError("Invalid pending recommendation")
    if not isinstance(pending["prompt_hash"], str) or not isinstance(
        pending["active_profile"], dict
    ):
        raise ValueError("Invalid pending recommendation")
    if (
        not isinstance(pending["result"], dict)
        or pending["result"].get("decision") not in RECOMMENDATIONS
    ):
        raise ValueError("Invalid pending recommendation")
    return pending


def save_pending(path: Path, request: dict[str, Any], result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = {
        "prompt_hash": prompt_hash(request["task"]),
        "active_profile": request["active_profile"],
        "result": result,
    }
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temporary_path = Path(output.name)
            json.dump(data, output, ensure_ascii=False)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def recommended_profile(pending: dict[str, Any]) -> dict[str, Any]:
    active = pending["active_profile"]
    result = pending["result"]
    return {
        field: result.get(f"recommended_{field}") or active[field]
        for field in ("model", "effort", "speed")
    }


def decide(
    request: dict[str, Any], path: Path, observe: Callable[[str], None] | None = None
) -> dict[str, Any] | None:
    pending = load_pending(path)
    if pending is not None and pending["prompt_hash"] != prompt_hash(request["task"]):
        try:
            path.unlink()
        except OSError:
            if observe is not None:
                observe("blocked_state_error")
            return {
                "decision": "block",
                "reason": (
                    "Model Fit: не удалось сбросить рекомендацию для предыдущего запроса. "
                    "Повтори запрос после восстановления локального состояния hook."
                ),
            }
        pending = None
    if pending is not None and pending["prompt_hash"] == prompt_hash(request["task"]):
        if pending["active_profile"] == request["active_profile"]:
            if observe is not None:
                observe("cached_" + pending["result"]["decision"])
            return hook_output(pending["result"])
        if recommended_profile(pending) == request["active_profile"]:
            path.unlink(missing_ok=True)
            if observe is not None:
                observe("selected")
            return None
    result = triage(request)
    if observe is not None:
        observe(result["decision"])
    output = hook_output(result)
    if result["decision"] in RECOMMENDATIONS:
        try:
            save_pending(path, request, result)
        except OSError:
            if observe is not None:
                observe("pending_save_error")
            assert output is not None and output.get("decision") == "block"
            output["reason"] += (
                " Состояние паузы не сохранилось; при повторе проверка запустится заново."
            )
    elif result["decision"] == "keep":
        path.unlink(missing_ok=True)
    return output


def main() -> int:
    pilot_thread = os.environ.get(PILOT_THREAD_ENV)
    turn_id = None
    try:
        event = json.load(sys.stdin)
        if (
            not isinstance(event, dict)
            or event.get("hook_event_name") != "UserPromptSubmit"
        ):
            return 0
        if not pilot_thread or event.get("session_id") != pilot_thread:
            return 0
        turn_id = event.get("turn_id")
        record_audit(pilot_thread, turn_id, "started")
        output = decide(
            session_input(event),
            pending_path(pilot_thread),
            lambda outcome: record_audit(pilot_thread, turn_id, outcome),
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        TimeoutError,
        subprocess.SubprocessError,
    ) as error:
        output = {
            "systemMessage": "Model Fit: hook не получил проверенное решение; профиль не оценён."
        }
        if pilot_thread:
            record_audit(pilot_thread, turn_id, f"error:{type(error).__name__}")
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
