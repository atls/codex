"""Trust candidate-only temporary hooks, then run exactly two native media rows."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SUITE = ROOT / "evals/model-fit"
sys.path.insert(0, str(ROOT / "plugins/model-fit/src"))
sys.path.insert(0, str(SUITE))
from model_fit.infrastructure.adapters.codex.authentication import authenticated_home
from model_fit.infrastructure.adapters.codex.history import (
    unavailable_session_input,
)
from model_fit.infrastructure.adapters.codex.transport.connection import (
    AppServerConnection,
    AppServerRPCError,
)

from acceptance.configuration import build_config

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
            "features.plugins=true",
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


def candidate_hooks(app, plugin, cwd, command):
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
            or hook.get("pluginId") != "model-fit@media-acceptance"
            or hook.get("async", False)
            or hook["source"] != "plugin"
            or Path(hook["sourcePath"]).resolve()
            != (plugin / "hooks/hooks.json").resolve()
            or hook["handlerType"] != "command"
            or hook["command"] != command
            or not isinstance(hook["currentHash"], str)
            or not hook["currentHash"]
        ):
            raise RuntimeError("Hook is not the exact candidate command/source")
    return hooks


def trust(home, workspace, codex, command, plugin):
    with connect(home, workspace, codex) as app:
        hooks = candidate_hooks(app, plugin, workspace, command)
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
        first = candidate_hooks(app, plugin, workspace, command)
    with connect(home, workspace, codex) as app:
        fresh = candidate_hooks(app, plugin, workspace, command)
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


def install_candidate(home, codex):
    market = home / "candidate-marketplace"
    source = market / "plugins/model-fit"
    shutil.copytree(
        ROOT / "plugins/model-fit",
        source,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".venv", "build", "dist", "*.egg-info"
        ),
    )
    shutil.copyfile(
        Path(__file__).with_name("capture_hook.py"), source / "scripts/capture_hook.py"
    )
    definition = source / "hooks/hooks.json"
    hooks = json.loads(definition.read_text())
    for entries in hooks["hooks"].values():
        for entry in entries:
            for hook in entry["hooks"]:
                hook["command"] = hook["command"].replace(
                    "scripts/desktop.py", "scripts/capture_hook.py"
                )
    definition.write_text(json.dumps(hooks))
    index = market / ".agents/plugins/marketplace.json"
    index.parent.mkdir(parents=True)
    index.write_text(
        json.dumps(
            {
                "name": "media-acceptance",
                "plugins": [
                    {
                        "name": "model-fit",
                        "source": {"source": "local", "path": "./plugins/model-fit"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Developer Tools",
                    }
                ],
            }
        )
    )
    (home / "config.toml").write_text(
        "[features]\nhooks=true\nplugins=true\napps=false\nshell_snapshot=false\n"
    )
    for command in (
        [codex, "plugin", "marketplace", "add", str(market), "--json"],
        [codex, "plugin", "add", "model-fit@media-acceptance", "--json"],
    ):
        subprocess.run(
            command,
            env=os.environ | {"CODEX_HOME": str(home)},
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    version = json.loads((source / ".codex-plugin/plugin.json").read_text())["version"]
    plugin = (home / "plugins/cache/media-acceptance/model-fit" / version).resolve()
    subprocess.run(
        ["uv", "sync", "--locked", "--project", str(plugin)],
        capture_output=True,
        check=True,
        timeout=60,
    )
    command = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"].replace(
        "${PLUGIN_ROOT}", str(plugin)
    )
    return plugin, command


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
                plugin, command = install_candidate(home, codex)
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
                readback = trust(home, workspace, codex, command, plugin)
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
                    "plugin": str(plugin),
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
