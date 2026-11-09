"""Install the distributable plugin through the native marketplace."""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from model_fit.infrastructure.adapters.codex.transport.connection import (
    AppServerConnection,
)


@unittest.skipUnless(shutil.which("codex"), "Codex CLI required")
class PluginInstallationTests(unittest.TestCase):
    def test_native_install_trust_and_revoke_cached_hook_commands(self):
        for marketplace in ("agent-tools", "regression-fixtures"):
            with self.subTest(marketplace=marketplace):
                self.install_trust_and_revoke(marketplace)

    def install_trust_and_revoke(self, marketplace):
        repository = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory(prefix="model-fit-plugin-test-") as directory:
            home = Path(directory) / "home"
            home.mkdir()
            (home / "config.toml").write_text(
                "[features]\nplugin_discovery_prefetch = false\n"
            )
            marketplace_root = Path(directory) / "marketplace"
            index = marketplace_root / ".agents/plugins/marketplace.json"
            index.parent.mkdir(parents=True)
            definition = json.loads(
                (repository / ".agents/plugins/marketplace.json").read_text()
            )
            definition["name"] = marketplace
            definition["plugins"][0]["source"]["path"] = "./plugins/model-fit"
            index.write_text(json.dumps(definition))
            shutil.copytree(
                repository / "plugins/model-fit",
                marketplace_root / "plugins/model-fit",
                ignore=shutil.ignore_patterns(
                    ".venv", "__pycache__", "*.egg-info", ".ruff_cache", "dist"
                ),
            )
            plugin_id = "model-fit@" + marketplace
            environment = {**os.environ, "CODEX_HOME": str(home)}
            for command in (
                [
                    "codex",
                    "plugin",
                    "marketplace",
                    "add",
                    str(marketplace_root),
                    "--json",
                ],
                ["codex", "plugin", "add", plugin_id, "--json"],
            ):
                installed = subprocess.run(
                    command,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(installed.returncode, 0, installed.stderr)
            process = subprocess.Popen(
                [
                    "codex",
                    "app-server",
                    "--listen",
                    "stdio://",
                    "-c",
                    "features.hooks=true",
                ],
                env=environment,
                cwd=directory,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            with AppServerConnection(
                process, {"name": "model_fit_plugin_test", "version": "1"}
            ) as app:
                effective = app.call("config/read", {"includeLayers": False}, 10)[
                    "config"
                ]
                self.assertFalse(effective["features"]["plugin_discovery_prefetch"])
                groups = app.call("hooks/list", {"cwds": [directory]}, 10)["data"]
                hooks = [hook for group in groups for hook in group["hooks"]]
                self.assertEqual(
                    {hook["eventName"] for hook in hooks},
                    {"userPromptSubmit", "preToolUse", "stop"},
                )
                self.assertTrue(
                    all(
                        (
                            hook["source"] == "plugin"
                            and hook["trustStatus"] == "untrusted"
                            for hook in hooks
                        )
                    )
                )
                skills = app.call(
                    "skills/list", {"cwds": [directory], "forceReload": True}, 10
                )["data"]
                selected = [
                    skill
                    for group in skills
                    for skill in group["skills"]
                    if skill.get("pluginId") == plugin_id
                ]
                self.assertEqual(len(selected), 1)
                self.assertTrue(Path(selected[0]["path"]).is_file())
            plugin = next(
                (home / "plugins/cache" / marketplace / "model-fit").glob("*")
            )
            environment["CODEX_PLUGIN_ROOT"] = str(plugin)
            self.assertFalse((plugin / "skills/model-fit/src").exists())
            manifest = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
            self.assertEqual(manifest["hooks"], "./hooks/hooks.json")
            subprocess.run(
                ["uv", "sync", "--locked", "--project", str(plugin)],
                env=environment,
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--quiet",
                    "--project",
                    str(plugin),
                    "python",
                    str(plugin / "scripts/desktop.py"),
                    "--help",
                ],
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("queue", result.stdout)
            plugin_python = plugin / ".venv/bin/python3"
            native_command = [
                "uv",
                "run",
                "--quiet",
                "--project",
                str(plugin),
                "python",
                str(plugin / "scripts/desktop.py"),
                "hook",
            ]
            event = {
                "session_id": "fixture-thread",
                "turn_id": "fixture-turn",
                "hook_event_name": "UserPromptSubmit",
                "cwd": directory,
                "model": "gpt-6-luna",
                "prompt": "fixture input",
            }
            with self.assertRaises(FileNotFoundError):
                (home / ".tmp/model-fit-auto-switch/fixture-thread.json").read_bytes()
            process = subprocess.Popen(
                [
                    "codex",
                    "app-server",
                    "--listen",
                    "stdio://",
                    "-c",
                    "features.hooks=true",
                ],
                env=environment,
                cwd=directory,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            with AppServerConnection(
                process, {"name": "model_fit_revoke_test", "version": "1"}
            ) as app:
                hooks = [
                    h
                    for g in app.call("hooks/list", {"cwds": [directory]}, 10)["data"]
                    for h in g["hooks"]
                ]
                edits = [
                    {
                        "keyPath": "features.hooks",
                        "value": True,
                        "mergeStrategy": "replace",
                    }
                ]
                if marketplace != "agent-tools":
                    edits.append(
                        {
                            "keyPath": "plugins."
                            + json.dumps("model-fit@agent-tools")
                            + ".enabled",
                            "value": False,
                            "mergeStrategy": "replace",
                        }
                    )
                edits.extend(
                    (
                        {
                            "keyPath": "hooks.state." + json.dumps(h["key"]),
                            "value": {
                                "enabled": True,
                                "trusted_hash": h["currentHash"],
                            },
                            "mergeStrategy": "replace",
                        }
                        for h in hooks
                    )
                )
                app.call(
                    "config/batchWrite", {"edits": edits, "reloadUserConfig": True}, 10
                )
                active = subprocess.run(
                    native_command,
                    input=json.dumps(event),
                    cwd=directory,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertIn(
                    "has not assessed",
                    json.loads(active.stdout)["hookSpecificOutput"][
                        "additionalContext"
                    ],
                )
                for issuing, guarding in (("python", "python3"), ("python3", "python")):
                    with self.subTest(issuing=issuing, guarding=guarding):
                        event["hook_event_name"] = "UserPromptSubmit"
                        issuer = [
                            str(plugin / ".venv/bin" / issuing),
                            "-m",
                            "model_fit.entrypoints.hooks.cli",
                            "hook",
                        ]
                        response = subprocess.run(
                            issuer,
                            input=json.dumps(event),
                            cwd=directory,
                            env=environment,
                            capture_output=True,
                            text=True,
                            check=True,
                        )
                        command = shlex.join(
                            [
                                str(plugin / ".venv/bin/python"),
                                "-m",
                                "model_fit.entrypoints.hooks.cli",
                                "assess",
                            ]
                        )
                        self.assertIn(
                            "`" + command + "`",
                            json.loads(response.stdout)["hookSpecificOutput"][
                                "additionalContext"
                            ],
                        )
                        check = {
                            **event,
                            "hook_event_name": "PreToolUse",
                            "tool_name": "Bash",
                            "tool_input": {"command": command},
                        }
                        guard = [
                            str(plugin / ".venv/bin" / guarding),
                            "-m",
                            "model_fit.entrypoints.hooks.cli",
                            "hook",
                        ]
                        permitted = subprocess.run(
                            guard,
                            input=json.dumps(check),
                            cwd=directory,
                            env=environment,
                            capture_output=True,
                            text=True,
                            check=True,
                        )
                        self.assertEqual(permitted.stdout, "")
                state = home / ".tmp/model-fit-auto-switch/fixture-thread.json"
                audit = home / ".tmp/model-fit-hook-audit/fixture-thread.jsonl"
                before = {
                    p: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (state, audit)
                }
                app.call(
                    "config/batchWrite",
                    {
                        "edits": [
                            {
                                "keyPath": "hooks.state."
                                + json.dumps(h["key"])
                                + ".enabled",
                                "value": False,
                                "mergeStrategy": "replace",
                            }
                            for h in hooks
                        ],
                        "reloadUserConfig": True,
                    },
                    10,
                )
                for name in ("UserPromptSubmit", "PreToolUse", "Stop"):
                    event["hook_event_name"] = name
                    result = subprocess.run(
                        native_command,
                        input=json.dumps(event),
                        cwd=directory,
                        env=environment,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    if name == "UserPromptSubmit":
                        self.assertIn("disabled", result.stdout.casefold())
                    else:
                        self.assertEqual(result.stdout, "")
                stale = subprocess.run(
                    [
                        str(plugin_python),
                        "-m",
                        "model_fit.entrypoints.hooks.cli",
                        "assess",
                    ],
                    cwd=directory,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertIn("disabled", stale.stdout.casefold())
                rejected = subprocess.run(
                    [
                        str(plugin_python),
                        "-m",
                        "model_fit.entrypoints.hooks.cli",
                        "queue",
                        "--thread-id",
                        "current",
                        "--turn-id",
                        "source",
                    ],
                    cwd=directory,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(json.loads(rejected.stdout)["status"], "disabled")
                feature_off = [
                    {
                        "keyPath": "features.hooks",
                        "value": False,
                        "mergeStrategy": "replace",
                    }
                ]
                feature_off.extend(
                    (
                        {
                            "keyPath": "hooks.state."
                            + json.dumps(h["key"])
                            + ".enabled",
                            "value": True,
                            "mergeStrategy": "replace",
                        }
                        for h in hooks
                    )
                )
                app.call(
                    "config/batchWrite",
                    {"edits": feature_off, "reloadUserConfig": True},
                    10,
                )
                event["hook_event_name"] = "UserPromptSubmit"
                result = subprocess.run(
                    native_command,
                    input=json.dumps(event),
                    cwd=directory,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertIn("disabled", result.stdout.casefold())
                for path, value in before.items():
                    self.assertEqual(
                        hashlib.sha256(path.read_bytes()).hexdigest(), value
                    )
