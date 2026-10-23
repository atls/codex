"""Run one isolated Model Fit case without changing project state."""

from __future__ import annotations
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from model_fit_evals.context import AppServer
from model_fit_evals.events import observe
from model_fit_evals.files import (
    checked_fixture_path,
    fixture_context,
    fixture_instructions,
    hash_text,
)


def run_case(
    case: dict[str, Any],
    skill_dir: Path,
    output_dir: Path,
    schema: dict[str, Any],
    model: str,
    effort: str,
    timeout: int,
    sources: str,
    controller: Any | None = None,
    catalog: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    case_dir = output_dir / case["id"]
    case_dir.mkdir()
    if case.get("source_failure"):
        output = {
            "active_model": case["model"],
            "active_effort": case["effort"],
            "active_speed": case["speed"],
            "decision": "unknown",
            "recommended_model": None,
            "recommended_effort": None,
            "recommended_speed": None,
            "official_source_url": None,
            "official_guidance": None,
            "task_inference": None,
            "reason": f"Required source unavailable: {case['source_failure']}",
        }
        (case_dir / "trace.jsonl").write_text(
            json.dumps(
                {
                    "event": "preflight_source_unavailable",
                    "source": case["source_failure"],
                }
            )
            + "\n"
        )
        return {
            "id": case["id"],
            "source": case["source"],
            "expected": case["expected"],
            "active_profile": {key: case[key] for key in ("model", "effort", "speed")},
            "skill_input": "not invoked: required source unavailable",
            "status": "completed",
            "elapsed_ms": 0,
            "prompt_sha256": hash_text(case["prompt"]),
            "observed": {
                "messages": [json.dumps(output)],
                "tool_types": [],
                "usage": None,
            },
        }
    if controller is not None and not case.get("implicit_selection_control"):
        active = {key: case[key] for key in ("model", "effort", "speed")}
        request = {"task": case["task_prompt"], "active_profile": active}
        if case.get("prior_choice"):
            request["prior_choice"] = {
                "user_selected": True,
                "same_work": True,
                "profile": active,
            }
        if context := fixture_context(case):
            request["context"] = context
        diagnostics: dict[str, Any] = {}
        started = time.monotonic()
        try:
            output = controller.run(
                request, model, effort, timeout, (sources, catalog), diagnostics
            )
        finally:
            if "events" in diagnostics:
                (case_dir / "trace.jsonl").write_text(
                    "".join(
                        json.dumps(event, ensure_ascii=False) + "\n"
                        for event in diagnostics["events"]
                    )
                )
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return {
            "id": case["id"],
            "source": case["source"],
            "expected": case["expected"],
            "active_profile": active,
            "skill_input": (
                "confirmed user choice bypass"
                if diagnostics.get("user_choice_bypass")
                else "hidden controller skill item"
            ),
            "status": "completed",
            "elapsed_ms": elapsed_ms,
            "prompt_sha256": diagnostics["prompt_sha256"],
            "observed": {
                "messages": [json.dumps(output, ensure_ascii=False)],
                "tool_types": diagnostics["tool_types"],
                "usage": diagnostics["usage"],
                "skill_item_seen": diagnostics["skill_item_seen"],
                "task_tool_seen": False,
                "hidden_agent_messages": diagnostics["agent_messages"],
            },
        }
    with tempfile.TemporaryDirectory(prefix="model-fit-triage-") as scratch_name:
        scratch = Path(scratch_name)
        subprocess.run(["git", "init", "-q", str(scratch)], check=True)
        if case.get("fixture_directory"):
            fixture = checked_fixture_path(case["fixture_directory"])
            shutil.copytree(fixture, scratch, dirs_exist_ok=True)
        started = time.monotonic()
        with AppServer(scratch, skill_dir, case_dir / "stderr.log") as app:
            listed = app.call(
                "skills/list", {"cwds": [str(scratch)], "forceReload": True}, 15
            )
            available = [
                skill
                for group in listed.get("data", [])
                for skill in group.get("skills", [])
            ]
            if not any(
                skill.get("name") == "model-fit"
                and skill.get("enabled") is True
                and Path(skill.get("path", "")).resolve() == app.skill_file.resolve()
                for skill in available
            ):
                raise RuntimeError(
                    "Candidate Model Fit is absent from app-server skills/list"
                )
            implicit = bool(case.get("implicit_selection_control"))
            instructions = (
                "This is an isolated read-only evaluation. Do not mutate files or external systems."
                if implicit
                else fixture_instructions(case) + " " + sources
            )
            thread = app.call(
                "thread/start",
                {
                    "model": model,
                    "cwd": str(scratch),
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "developerInstructions": instructions,
                },
                15,
            )["thread"]
            turn_input = [{"type": "text", "text": case["prompt"]}]
            if not implicit:
                turn_input.append(
                    {"type": "skill", "name": "model-fit", "path": str(app.skill_file)}
                )
            turn_params = {
                "threadId": thread["id"],
                "input": turn_input,
                "effort": effort,
                "sandboxPolicy": {"type": "readOnly"},
            }
            if not implicit:
                turn_params["outputSchema"] = schema
            response = app.call("turn/start", turn_params, 15)
            status = app.wait_turn(thread["id"], response["turn"]["id"], timeout)
            events = app.events
            observed = observe(events, app.skill_file)
        elapsed_ms = round((time.monotonic() - started) * 1000)
    (case_dir / "trace.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
    )
    return {
        "id": case["id"],
        "source": case["source"],
        "expected": case["expected"],
        "active_profile": {key: case[key] for key in ("model", "effort", "speed")},
        "skill_input": "implicit selection control"
        if case.get("implicit_selection_control")
        else "explicit app-server skill item",
        "status": status,
        "elapsed_ms": elapsed_ms,
        "prompt_sha256": hash_text(case["prompt"]),
        "observed": observed,
    }
