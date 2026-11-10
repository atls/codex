from model_fit.infrastructure.adapters.codex.transport.assessment.types.runtime import (
    AssessmentRuntimeFactory,
)
import json
from model_fit.application.submission.constraints.content import (
    checked_object,
    checked_content,
    native_text,
)
from importlib.resources import files
from pathlib import Path
from model_fit.application.submission.types.json import JsonValue
from model_fit.application.assessment.types.profile import ActiveProfile
from model_fit.application.assessment.types.work_relation import WorkRelation

from model_fit.infrastructure.adapters.codex.transport.assessment.response import (
    assessment_response,
)
from model_fit.infrastructure.adapters.codex.transport.assessment.workspace import (
    assessment_workspace,
)

SCHEMA = files("model_fit.application.assessment").joinpath("decision.schema.json")


def execute_assessment(
    instructions: str,
    prompt: str,
    evaluator_model: str,
    evaluator_effort: str,
    timeout: int,
    diagnostics: dict[str, JsonValue] | None,
    codex_path: str,
    runtime_factory: AssessmentRuntimeFactory,
    skill_directory: Path | None,
    *,
    native_input: list[dict[str, JsonValue]] | None = None,
    active_profile: ActiveProfile,
) -> dict[str, JsonValue]:
    schema = checked_object(json.loads(SCHEMA.read_text()))
    properties = checked_object(schema["properties"])
    properties["work_relation"] = {
        "type": "string",
        "enum": [relation.value for relation in WorkRelation],
    }
    required = schema["required"]
    if not isinstance(required, list):
        raise ValueError("Assessment schema required fields are unavailable")
    required.append("work_relation")
    if active_profile["speed"] is None:
        for field in ("active_speed", "recommended_speed"):
            properties[field] = {"type": "null"}
    with assessment_workspace() as scratch:
        runtime_options = (
            {"skill_dir": skill_directory} if skill_directory is not None else {}
        )
        with runtime_factory(scratch, codex_path=codex_path, **runtime_options) as app:
            try:
                listed = app.call(
                    "skills/list", {"cwds": [str(scratch)], "forceReload": True}, 15
                )
                available = [
                    skill
                    for group in checked_content(listed.get("data", []))
                    for skill in checked_content(group.get("skills", []))
                ]
                if not any(
                    (
                        skill.get("name") == "model-fit"
                        and skill.get("enabled") is True
                        and (
                            Path(native_text(skill.get("path", ""))).resolve()
                            == app.skill_file.resolve()
                        )
                        for skill in available
                    )
                ):
                    raise RuntimeError(
                        "Model Fit is absent from app-server skills/list"
                    )
                thread = checked_object(
                    app.call(
                        "thread/start",
                        {
                            "model": evaluator_model,
                            "cwd": str(scratch),
                            "approvalPolicy": "never",
                            "sandbox": "read-only",
                            "ephemeral": True,
                            "developerInstructions": instructions,
                        },
                        15,
                    )["thread"]
                )
                response = app.call(
                    "turn/start",
                    {
                        "threadId": thread["id"],
                        "input": [
                            {"type": "text", "text": prompt},
                            *(native_input or []),
                            {
                                "type": "skill",
                                "name": "model-fit",
                                "path": str(app.skill_file),
                            },
                        ],
                        "effort": evaluator_effort,
                        "sandboxPolicy": {"type": "readOnly"},
                        "outputSchema": schema,
                    },
                    15,
                )
                status = app.wait_turn(
                    native_text(thread["id"]),
                    native_text(checked_object(response["turn"])["id"]),
                    timeout,
                )
                events = app.events
            finally:
                if diagnostics is not None:
                    diagnostics["events"] = list[JsonValue](app.events)
                    diagnostics["usage"] = next(
                        (
                            checked_object(event.get("params") or {}).get("tokenUsage")
                            for event in reversed(app.events)
                            if event.get("method") == "thread/tokenUsage/updated"
                        ),
                        None,
                    )
    if status != "completed":
        raise RuntimeError(f"Preflight turn ended with {status}")
    output = assessment_response(events, app.skill_file, diagnostics)
    return output
