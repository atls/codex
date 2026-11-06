"""Native Promptfoo configuration for an explicitly trusted media case."""

import json
from pathlib import Path


def build_config(manifest):
    if manifest.get("trustReadbackPassed") is not True:
        raise ValueError("Native trust/readback must pass before provider construction")
    return {
        "description": "Isolated native-host media acceptance",
        "prompts": ["{{input}}"],
        "providers": [
            {
                "id": "openai:codex-app-server",
                "env": {"OPENAI_API_KEY": "", "CODEX_API_KEY": ""},
                "config": {
                    "model": "gpt-6-luna",
                    "model_reasoning_effort": "medium",
                    "codex_path_override": manifest["codex"],
                    "cli_env": {
                        "CODEX_HOME": manifest["home"],
                        "HOME": manifest["home"],
                        "PATH": manifest["path"],
                    },
                    "cli_config": {
                        "features": {
                            "hooks": True,
                            "apps": False,
                            "plugins": False,
                            "shell_snapshot": False,
                        },
                        "allow_login_shell": False,
                    },
                    "inherit_process_env": False,
                    "working_dir": manifest["workspace"],
                    "sandbox_mode": "read-only",
                    "approval_policy": "never",
                    "network_access_enabled": False,
                    "ephemeral": True,
                    "persist_threads": False,
                    "reuse_server": False,
                    "include_raw_events": True,
                    "experimental_raw_events": True,
                    "turn_timeout_ms": 180000,
                    "developer_instructions": "This is an isolated visual acceptance task. Describe the dominant color of each supplied image in input order. Return JSON with colors (two simple lowercase color names) and imageCount. Do not use tools, skills, profile selection or external services.",
                    "output_schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["colors", "imageCount"],
                        "properties": {
                            "colors": {
                                "type": "array",
                                "minItems": 2,
                                "maxItems": 2,
                                "items": {"type": "string"},
                            },
                            "imageCount": {"type": "integer"},
                        },
                    },
                },
            }
        ],
        "tests": [
            {
                "description": manifest["id"],
                "vars": {
                    "input": json.dumps(manifest["input"]),
                    "home": manifest["home"],
                    "evidence": manifest["evidence"],
                    "prompt": manifest["prompt"],
                    "workspace": manifest["workspace"],
                    "retained_images": manifest.get("retainedImages", []),
                },
                "assert": [
                    {
                        "type": "python",
                        "value": "file://" + str(Path(__file__).with_name("grade.py")),
                    }
                ],
            }
        ],
        "evaluateOptions": {"maxConcurrency": 1, "cache": False},
    }
