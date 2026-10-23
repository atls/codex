"""Read the active profile and run one isolated recommendation."""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from model_fit.app_server import AppServerReader


def session_input(event: dict[str, Any]) -> dict[str, Any]:
    session_id = event.get("session_id")
    prompt = event.get("prompt")
    cwd = event.get("cwd")
    model = event.get("model")
    if not all(
        isinstance(value, str) and value for value in (session_id, cwd, model)
    ) or not isinstance(prompt, str):
        raise ValueError("Incomplete Desktop hook input")
    with AppServerReader(cwd) as app:
        thread = app.call(
            "thread/read", {"threadId": session_id, "includeTurns": False}, 10
        )["thread"]
        effort = thread.get("reasoningEffort")
        if thread.get("model") != model or not isinstance(effort, str):
            raise ValueError("Active model or reasoning effort is unavailable")
        turns = app.call(
            "thread/turns/list",
            {"threadId": session_id, "limit": 5, "itemsView": "summary"},
            10,
        ).get("data", [])
    recent = []
    for turn in turns:
        for item in turn.get("items", []):
            if item.get("type") != "userMessage":
                continue
            text = "\n".join(
                content.get("text", "")
                for content in item.get("content", [])
                if content.get("type") == "text"
                and isinstance(content.get("text"), str)
            ).strip()
            if text and text != prompt.strip():
                recent.append(text)
        if len(recent) >= 3:
            break
    request = {
        "task": prompt
        or "Запрос с вложениями без текстового описания; учитывай контекст текущей работы.",
        "active_profile": {
            "model": model,
            "effort": effort,
            "speed": None,
        },
    }
    if recent:
        request["context"] = (
            "Предыдущие запросы пользователя как контекст:\n"
            + "\n\n".join(recent[:3])[:12000]
        )
    return request


def triage(request: dict[str, Any]) -> dict[str, Any]:
    process = subprocess.run(
        [sys.executable, str(TRIAGE), "--timeout", "45"],
        input=json.dumps(request, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=75,
    )
    result = json.loads(process.stdout)
    if not isinstance(result, dict) or result.get("decision") not in (
        RECOMMENDATIONS | {"keep", "unknown"}
    ):
        raise ValueError("Triage returned an invalid decision")
    for field in ("model", "effort", "speed"):
        if result.get(f"active_{field}") != request["active_profile"][field]:
            raise ValueError("Triage changed the active profile")
    if process.returncode not in (0, 1) or (process.returncode == 1) != (
        result["decision"] == "unknown"
    ):
        raise ValueError("Triage exit status contradicts its decision")
    return result


def hook_output(result: dict[str, Any]) -> dict[str, Any] | None:
    decision = result["decision"]
    if decision == "keep":
        return None
    if decision == "unknown":
        return {
            "systemMessage": "Model Fit: проверка профиля не завершилась; пригодность не установлена."
        }
    if decision not in RECOMMENDATIONS:
        raise ValueError("Unsupported triage decision")
    model = result.get("recommended_model") or result["active_model"]
    effort = result.get("recommended_effort") or result["active_effort"]
    source = result.get("official_source_url")
    guidance = result.get("official_guidance")
    inference = result.get("task_inference")
    if not all(
        isinstance(value, str) and value
        for value in (model, effort, source, guidance, inference)
    ):
        raise ValueError("Incomplete triage recommendation")
    return {
        "decision": "block",
        "reason": (
            f"Model Fit: переключи профиль на {model} / {effort} и повтори этот запрос. "
            f"Рекомендация OpenAI: {guidance} Вывод для этой задачи: {inference} "
            f"Источник: {source}"
        ),
    }


TRIAGE = Path(__file__).resolve().parents[1] / "triage.py"

RECOMMENDATIONS = {"recommend_lighter", "recommend_stronger", "recommend_faster"}
