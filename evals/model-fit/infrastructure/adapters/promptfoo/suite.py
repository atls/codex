"""Promptfoo suite data assembled by the Python evaluation owners."""

import hashlib
import json
import os
from pathlib import Path

from assessment.scenarios import generate_tests
from autoswitch.execution.scenarios import execution_cases
from infrastructure.adapters.codex.session import PROVIDER_ENV, SUITE


def read_json(path):
    return json.loads(Path(path).read_text())


def suite_cases(surface):
    if surface == "tasks":
        return execution_cases()
    return [{"id": "generated-tests"}]


def provider(runtime, **config):
    return {
        "id": "openai:codex-app-server",
        "env": PROVIDER_ENV,
        "config": {**runtime["config"], **config},
    }


def build_suite(surface, runtime):
    if surface == "tasks":
        return task_suite(runtime)
    generator = {
        "surface": surface,
        "workspace_root": runtime["workspaces"]["generated-tests"],
        "judge": runtime["judge"],
    }
    if surface == "native":
        generator["skill_file"] = runtime["skill"]
    if surface == "regrade" and os.environ.get("MODEL_FIT_REGRADE_FILE"):
        generator["saved_result"] = os.environ["MODEL_FIT_REGRADE_FILE"]
    prompts = {
        "native": "{{input}}",
        "assessment": "{{input}}",
        "ordinary": "{{task}}",
        "calibration": "{{answer}}",
        "regrade": "{{answer}}",
    }
    config = {
        "description": "Model Fit " + surface,
        "prompts": [prompts[surface]],
        "tests": generate_tests(generator),
    }
    if surface in {"calibration", "regrade"}:
        config["providers"] = ["echo"]
    elif surface == "assessment":
        config["metadata"] = {
            "surface": "profile-assessment",
            "codexVersion": runtime["version"],
            "promptfooVersion": "0.125.1",
        }
        config["providers"] = [
            {
                "id": "file://infrastructure/adapters/promptfoo/provider.py",
                "env": {**runtime["config"]["cli_env"], **PROVIDER_ENV},
                "config": {
                    "model": "gpt-6.1-sol",
                    "effort": "low",
                    "timeout": 240000,
                    "turn_timeout_seconds": 180,
                    "codex_path": runtime["executable"],
                },
            }
        ]
    elif surface == "ordinary":
        config["providers"] = [
            provider(
                runtime,
                developer_instructions="Answer the user question. This is a read-only evaluation.",
            )
        ]
    else:
        schema = read_json(
            SUITE.parents[1]
            / "src/vector_prime/application/assessment/decision.schema.json"
        )
        config["providers"] = [
            provider(
                runtime, output_schema=schema, developer_instructions="{{instructions}}"
            )
        ]
        config["metadata"] = {
            "surface": "isolated-native-skill",
            "codexVersion": runtime["version"],
            "promptfooVersion": "0.125.1",
            "skillSha256": hashlib.sha256(
                Path(runtime["skill"]).read_bytes()
            ).hexdigest(),
            "schemaSha256": hashlib.sha256(
                json.dumps(schema, separators=(",", ":"), ensure_ascii=False).encode()
            ).hexdigest(),
        }
    return config


def task_suite(runtime):
    instructions = "Complete only the supplied task. All necessary input is supplied. Use no tools, skills or external systems. Return only the requested JSON."
    tests = []
    for entry in execution_cases():
        assertions = [
            {"type": "is-json"},
            {"type": "python", "value": "file://autoswitch/execution/assertions.py"},
        ]
        if entry["rubric"]:
            assertions.append(
                {
                    "type": "llm-rubric",
                    "threshold": 1,
                    "value": entry["rubric"],
                    "provider": runtime["judge"],
                }
            )
        tests.append(
            {
                "description": entry["id"],
                "vars": {
                    "task": entry["task"],
                    "expected_outputs": entry["expected_outputs"],
                    "workspace": runtime["workspaces"][entry["id"]],
                },
                "assert": assertions,
            }
        )
    return {
        "description": "Fixed task execution without Model Fit selection",
        "metadata": {
            "surface": "stock-codex-task-execution",
            "codexVersion": runtime["version"],
            "promptfooVersion": "0.125.1",
        },
        "prompts": ["{{task}}"],
        "providers": [
            {
                **provider(
                    runtime,
                    model=model,
                    model_reasoning_effort=effort,
                    developer_instructions=instructions,
                ),
                "label": label,
            }
            for model, effort, label in [
                ("gpt-6.1-sol", "medium", "current-sol-medium"),
                ("gpt-6-luna", "low", "candidate-luna-low"),
            ]
        ],
        "tests": tests,
    }
