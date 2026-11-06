"""Trust candidate-only temporary hooks, then run exactly two native media rows."""

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SUITE = ROOT / "evals/model-fit"
sys.path.insert(0, str(ROOT / "plugins/model-fit/src"))
sys.path.insert(0, str(SUITE))
from acceptance.configuration import build_config
from model_fit.infrastructure.codex.transport.connection import (
    AppServerConnection,
    AppServerRPCError,
)
from model_fit.infrastructure.codex.conversation.queries import (
    unavailable_session_input,
)
from model_fit.infrastructure.codex.authentication import authenticated_home

EVENTS = {"userPromptSubmit", "preToolUse", "stop"}


def connect(home, cwd, codex):
    process = subprocess.Popen(
        [
            codex,
            "app-server",
            "--listen",
            "stdio://",
            "-c",
            "features.hooks=true",
            "-c",
            "features.plugins=false",
            "-c",
            "features.apps=false",
            "-c",
            "features.shell_snapshot=false",
        ],
        cwd=cwd,
        env=os.environ
        | {
            "CODEX_HOME": str(home),
            "HOME": str(home),
            "OPENAI_API_KEY": "",
            "CODEX_API_KEY": "",
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return AppServerConnection(
        process, {"name": "model_fit_native_acceptance", "version": "1"}
    )


def candidate_hooks(app, home, cwd, command):
    groups = app.call("hooks/list", {"cwds": [str(cwd)]}, 15)["data"]
    if len(groups) != 1 or groups[0].get("errors") or groups[0].get("warnings"):
        raise RuntimeError("Native hook inventory is not clean")
    hooks = groups[0]["hooks"]
    if (
        len(hooks) != 3
        or {h["eventName"] for h in hooks} != EVENTS
        or len({h["key"] for h in hooks}) != 3
    ):
        raise RuntimeError("Unexpected candidate hook inventory")
    for hook in hooks:
        if (
            hook.get("isManaged", False)
            or hook.get("pluginId") is not None
            or hook.get("async", False)
            or hook["source"] != "user"
            or Path(hook["sourcePath"]).resolve() != (home / "hooks.json").resolve()
            or hook["handlerType"] != "command"
            or hook["command"] != command
            or not isinstance(hook["currentHash"], str)
            or not hook["currentHash"]
            or not hook["key"].startswith(str(home / "hooks.json"))
        ):
            raise RuntimeError("Hook is not the exact candidate command/source")
    return hooks


def trust(home, workspace, codex, command):
    with connect(home, workspace, codex) as app:
        hooks = candidate_hooks(app, home, workspace, command)
        app.call(
            "config/batchWrite",
            {
                "edits": [
                    {
                        "keyPath": "hooks.state",
                        "value": {
                            h["key"]: {
                                "trusted_hash": h["currentHash"],
                                "enabled": True,
                            }
                            for h in hooks
                        },
                        "mergeStrategy": "upsert",
                    }
                ],
                "filePath": str(home / "config.toml"),
                "reloadUserConfig": True,
            },
            15,
        )
        first = candidate_hooks(app, home, workspace, command)
    with connect(home, workspace, codex) as app:
        fresh = candidate_hooks(app, home, workspace, command)
    expected = {(h["key"], h["currentHash"]) for h in hooks}
    if any(
        {(h["key"], h["currentHash"]) for h in result} != expected
        or any(not h["enabled"] or h["trustStatus"] != "trusted" for h in result)
        for result in [first, fresh]
    ):
        raise RuntimeError("Native trust is absent in same/fresh-process readback")
    return [
        {
            "key": h["key"],
            "hash": h["currentHash"],
            "eventName": h["eventName"],
            "enabled": h["enabled"],
            "trustStatus": h["trustStatus"],
        }
        for h in fresh
    ]


def capability_preflight(home, workspace, codex):
    with connect(home, workspace, codex) as owner:
        thread = owner.call(
            "thread/start",
            {
                "cwd": str(workspace),
                "model": "gpt-6-luna",
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "ephemeral": True,
            },
            15,
        )["thread"]
        thread_id = thread["id"]
        with connect(home, workspace, codex) as reader:
            try:
                reader.call(
                    "thread/read", {"threadId": thread_id, "includeTurns": False}, 10
                )
                reader.call(
                    "thread/turns/list",
                    {"threadId": thread_id, "limit": 5, "itemsView": "summary"},
                    10,
                )
            except AppServerRPCError as error:
                reason = unavailable_session_input(error, thread_id)
                if reason is not None:
                    return {"reasonCode": reason, "zeroTurnControl": True}
                raise
    raise RuntimeError(
        "Expected capability boundary absent; no media inference allowed"
    )


def main():
    source_home = Path(os.environ["CODEX_EVAL_HOME"])
    source_auth = source_home / "auth.json"
    original = source_auth.read_bytes()
    if json.loads(original).get("auth_mode") != "chatgpt":
        raise RuntimeError("Existing subscription authentication is required")
    codex = str(Path(shutil.which("codex")).resolve())
    image_python = os.environ["MODEL_FIT_IMAGE_PYTHON"]
    evidence = Path(os.environ["MODEL_FIT_ACCEPTANCE_OUTPUT"]).resolve()
    evidence.mkdir(mode=0o700, parents=True, exist_ok=False)
    stage = "prepare"
    report = {
        "scope": "native ephemeral host, not Desktop sidebar/full switch",
        "rows": [],
    }
    try:
        with ExitStack() as resources:
            manifests = []
            selected_rows = set(
                os.environ.get(
                    "MODEL_FIT_ACCEPTANCE_ROWS", "text-two-images,empty-two-images"
                ).split(",")
            )
            if not selected_rows or not selected_rows <= {
                "text-two-images",
                "empty-two-images",
            }:
                raise ValueError("Unknown acceptance row selection")
            for identifier, prompt in [
                (
                    "text-two-images",
                    "Report the dominant colors of these two images in input order.",
                ),
                ("empty-two-images", ""),
            ]:
                if identifier not in selected_rows:
                    continue
                with patch.dict(os.environ, {"CODEX_HOME": str(source_home)}):
                    home = Path(
                        resources.enter_context(
                            authenticated_home("model-fit-media-home-")
                        )
                    ).resolve()
                workspace = Path(
                    resources.enter_context(
                        tempfile.TemporaryDirectory(prefix="model-fit-media-work-")
                    )
                ).resolve()
                subprocess.run(["git", "init", "-q", str(workspace)], check=True)
                shutil.copytree(
                    ROOT / "plugins/model-fit",
                    home / "plugins/model-fit",
                    ignore=shutil.ignore_patterns(
                        "__pycache__", "*.pyc", ".venv", "build", "dist", "*.egg-info"
                    ),
                )
                shutil.copyfile(
                    Path(__file__).with_name("capture_hook.py"),
                    home / "capture_hook.py",
                )
                command = shlex.join([sys.executable, str(home / "capture_hook.py")])
                (home / "hooks.json").write_text(
                    json.dumps(
                        {
                            "hooks": {
                                event: [
                                    {
                                        "hooks": [
                                            {
                                                "type": "command",
                                                "command": command,
                                                "timeout": timeout,
                                            }
                                        ]
                                    }
                                ]
                                for event, timeout in [
                                    ("UserPromptSubmit", 360),
                                    ("PreToolUse", 10),
                                    ("Stop", 45),
                                ]
                            }
                        }
                    )
                )
                (home / "config.toml").write_text(
                    "[features]\nhooks = true\nplugins = false\napps = false\nshell_snapshot = false\n"
                )
                subprocess.run(
                    [
                        image_python,
                        str(Path(__file__).with_name("media.py")),
                        str(workspace),
                    ],
                    check=True,
                )
                stage = "trust:" + identifier
                if (
                    (home / "auth.json").is_symlink()
                    or (home / "auth.json").stat().st_mode & 0o777 != 0o600
                    or (
                        (home / "auth.json").stat().st_dev,
                        (home / "auth.json").stat().st_ino,
                    )
                    == (source_auth.stat().st_dev, source_auth.stat().st_ino)
                ):
                    raise RuntimeError("Private auth copy invariant failed")
                readback = trust(home, workspace, codex, command)
                capability = capability_preflight(home, workspace, codex)
                output = evidence / identifier
                output.mkdir(mode=0o700)
                retained_images = []
                for filename in ["first.png", "second.png"]:
                    source = workspace / filename
                    shutil.copyfile(source, output / filename)
                    retained_images.append(
                        {
                            "originalPath": str(source),
                            "retainedPath": str(output / filename),
                            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        }
                    )
                manifest = {
                    "id": identifier,
                    "home": str(home),
                    "workspace": str(workspace),
                    "codex": codex,
                    "path": os.environ["PATH"],
                    "prompt": prompt,
                    "evidence": str(output),
                    "trustReadbackPassed": True,
                    "retainedImages": retained_images,
                    "trust": readback,
                    "capability": capability,
                    "input": [
                        {"type": "text", "text": prompt},
                        {"type": "localImage", "path": str(workspace / "first.png")},
                        {"type": "localImage", "path": str(workspace / "second.png")},
                    ],
                    "codexVersion": subprocess.check_output(
                        [codex, "--version"], text=True
                    ).strip(),
                    "hookPythonVersion": sys.version.split()[0],
                    "candidateCommit": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                    ).strip(),
                }
                path = output / "manifest.json"
                path.write_text(json.dumps(manifest, indent=2))
                config_path = output / "config.json"
                config_path.write_text(json.dumps(build_config(manifest)))
                env = os.environ | {
                    "MODEL_FIT_ACCEPTANCE_MANIFEST": str(path),
                    "PROMPTFOO_PYTHON": image_python,
                    "PROMPTFOO_CONFIG_DIR": str(output / "promptfoo"),
                    "PROMPTFOO_DISABLE_TELEMETRY": "1",
                    "LOG_LEVEL": "warn",
                }
                check = subprocess.run(
                    [
                        "yarn",
                        "exec",
                        "promptfoo",
                        "validate",
                        "config",
                        "--config",
                        str(config_path),
                    ],
                    cwd=SUITE,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                (output / "validation.log").write_text(check.stdout + check.stderr)
                if check.returncode:
                    raise RuntimeError("Native acceptance config validation failed")
                manifests.append((manifest, env, config_path))
            if source_auth.read_bytes() != original:
                raise RuntimeError("Source login changed before acceptance")
            for manifest, env, config_path in manifests:
                stage = "native-row:" + manifest["id"]
                print(stage, flush=True)
                output = Path(manifest["evidence"])
                started = time.monotonic()
                result = subprocess.run(
                    [
                        "yarn",
                        "exec",
                        "promptfoo",
                        "eval",
                        "--config",
                        str(config_path),
                        "--no-cache",
                        "--max-concurrency",
                        "1",
                        "--output",
                        str(output / "result.json"),
                    ],
                    cwd=SUITE,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                (output / "stdout.log").write_text(result.stdout)
                (output / "stderr.log").write_text(result.stderr)
                for name in [
                    "acceptance-hook-events.jsonl",
                    ".tmp/model-fit-hook-audit",
                    ".tmp/model-fit-auto-switch",
                ]:
                    source = Path(manifest["home"]) / name
                    if source.is_dir():
                        shutil.copytree(
                            source,
                            output
                            / ("state" if name.endswith("auto-switch") else "audit"),
                        )
                    elif source.is_file():
                        shutil.copyfile(source, output / source.name)
                grade_file = output / "grade.json"
                grade = (
                    json.loads(grade_file.read_text())
                    if grade_file.exists()
                    else {"pass": False}
                )
                report["rows"].append(
                    {
                        "id": manifest["id"],
                        "candidateCommit": manifest["candidateCommit"],
                        "codexVersion": manifest["codexVersion"],
                        "hookPythonVersion": manifest["hookPythonVersion"],
                        "pass": grade["pass"],
                        "elapsedMs": round((time.monotonic() - started) * 1000),
                        **{
                            key: grade.get(key)
                            for key in [
                                "checks",
                                "colors",
                                "nativeInputItemTypes",
                                "nativeHookEventCount",
                                "auditOutcomes",
                                "launchModel",
                                "launchEffort",
                                "usageTotal",
                            ]
                        },
                    }
                )
                (evidence / "safe-report.json").write_text(json.dumps(report, indent=2))
                if result.returncode:
                    raise RuntimeError("Native acceptance row failed; no retry")
            if source_auth.read_bytes() != original:
                raise RuntimeError("Source login changed during acceptance")
            report["sourceAuthUnchanged"] = True
            report["completedRows"] = len(manifests)
            (evidence / "safe-report.json").write_text(json.dumps(report, indent=2))
            (evidence / "completion.json").write_text(
                json.dumps(
                    {
                        "completedRows": len(manifests),
                        "sourceAuthUnchanged": True,
                        "scope": "native ephemeral host, not Desktop sidebar or full switch/replay",
                    }
                )
            )
    except Exception as error:
        report.update(
            {
                "failedStage": stage,
                "errorType": type(error).__name__,
                "sourceAuthUnchanged": source_auth.read_bytes() == original,
            }
        )
        (evidence / "safe-report.json").write_text(json.dumps(report, indent=2))
        (evidence / "failure.json").write_text(
            json.dumps(
                {
                    "stage": stage,
                    "errorType": type(error).__name__,
                    "message": str(error),
                    "sourceAuthUnchanged": source_auth.read_bytes() == original,
                }
            )
        )
        raise


if __name__ == "__main__":
    main()
