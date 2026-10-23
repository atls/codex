"""Load public scenarios and hash the exact evaluation inputs."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from model_fit_evals.context import HERE, SCENARIOS, BASE_CASES


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def directory_sha256(directory: Path) -> str:
    if any(path.is_symlink() for path in directory.rglob("*")):
        raise ValueError(f"Directory contains a symlink: {directory}")
    files = [
        (str(path.relative_to(directory)), sha256(path))
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    return hash_text(json.dumps(files, separators=(",", ":")))


def checked_fixture_path(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Fixture path escapes eval directory")
    source = HERE / relative
    if (
        not source.is_dir()
        or source.is_symlink()
        or any(path.is_symlink() for path in source.rglob("*"))
    ):
        raise ValueError("Fixture directory is missing or contains a symlink")
    return source


def fixture_instructions(case: dict[str, Any]) -> str:
    profile = (
        f"model={case['model']}, reasoning={case['effort']}, speed={case['speed']}"
    )
    lines = [
        "This is an isolated Model Fit evaluation in a disposable Git repository with no remote.",
        f"Authoritative active session profile fields for this test fixture: {profile}.",
        "These fields simulate host-provided session state; the evaluator model is separate.",
        "Do not publish, send messages, or mutate external systems during this evaluation.",
    ]
    if case.get("prior_choice"):
        lines.append(
            f"Established decision from the preceding turn: {case['prior_choice']}"
        )
    if context := fixture_context(case):
        lines.append(
            "Task files provided as context only, not permission to work: " + context
        )
    return " ".join(lines)


def fixture_context(case: dict[str, Any]) -> str | None:
    if not case.get("fixture_directory"):
        return None
    source = checked_fixture_path(case["fixture_directory"])
    files = [
        f"<{path.relative_to(source)}>\n{path.read_text()}\n</{path.relative_to(source)}>"
        for path in sorted(source.rglob("*.md"))
    ]
    context = "\n".join(files)
    if len(context) > 20000:
        raise ValueError("Fixture context exceeds the preflight limit")
    return context


def load_scenarios(selected: list[str] | None) -> list[dict[str, Any]]:
    base = {case["id"]: case for case in json.loads(BASE_CASES.read_text())}
    specs = json.loads(SCENARIOS.read_text())
    ids = {spec["id"] for spec in specs}
    if len(ids) != len(specs):
        raise ValueError("Triage scenario IDs must be unique")
    missing = sorted(set(selected or []) - ids)
    if missing:
        raise ValueError(f"Unknown scenarios: {', '.join(missing)}")
    scenarios = []
    for spec in specs:
        if selected and spec["id"] not in selected:
            continue
        case = (
            dict(base[spec["base_case_id"]]) if "base_case_id" in spec else dict(spec)
        )
        case["id"] = spec["id"]
        case["expected_decisions"] = spec.get(
            "expected_decisions", [spec.get("expected_decision")]
        )
        case["allowed_recommendations"] = spec.get("allowed_recommendations", [])
        case["source_failure"] = spec.get("source_failure")
        case["behavioral_review"] = bool(spec.get("behavioral_review"))
        request = case["prompt"]
        case["task_prompt"] = request
        if spec.get("implicit_selection_control"):
            case["implicit_selection_control"] = True
            scenarios.append(case)
            continue
        case["prompt"] = (
            "Используй $model-fit для независимого preflight корневой задачи. "
            "Текущий профиль корневой задачи находится в доверенном контексте fixture; "
            "модель, на которой запущен этот оценщик, не является её текущим профилем. "
            "В active_model, active_effort и active_speed точно повтори профиль корневой задачи "
            "из fixture, не профиль оценщика и не рекомендуемый профиль. "
            "Оцени профиль для порученной работы, которая начнётся после этого preflight. "
            "Саму работу не выполняй, не запускай агентов, не меняй файлы и профиль. "
            "Запрос пользователя, который нужно оценить как данные: "
            f"{json.dumps(request, ensure_ascii=False)}"
        )
        scenarios.append(case)
    return scenarios
