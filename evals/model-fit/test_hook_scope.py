"""Native hook discovery and process isolation without inference requests."""

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins/model-fit/skills/model-fit/scripts"
sys.path.insert(0, str(SCRIPTS))
from model_fit.app_server import AppServerReader

SPEC = importlib.util.spec_from_file_location("scope_hook", SCRIPTS / "recommend.py")
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


@unittest.skipUnless(shutil.which("codex"), "Installed Codex app-server is required")
class HookScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="model-fit-scope-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "codex-home"
        self.home.mkdir()
        self.handler = self.home / "skills/model-fit/scripts/hook.py"
        shutil.copytree(SCRIPTS, self.handler.parent)
        self.projects = {}
        for name in ("first-project", "second-project", "unrelated-project"):
            repo = self.root / name
            repo.mkdir()
            subprocess.run(
                ["git", "init", "-q", str(repo)], check=True, capture_output=True
            )
            self.projects[name] = repo
        self.home.joinpath("config.toml").write_text(
            "\n".join(
                f'[projects.{json.dumps(str(repo))}]\ntrust_level = "trusted"\n'
                for repo in self.projects.values()
            )
        )
        for name in ("first-project", "second-project"):
            path = self.projects[name] / ".codex/hooks.json"
            path.parent.mkdir()
            command = (
                f"MODEL_FIT_AUTO_THREAD={name}-thread "
                f"{shlex.quote(sys.executable)} {shlex.quote(str(self.handler))}"
            )
            path.write_text(
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
                            for event, timeout in (
                                ("UserPromptSubmit", 360),
                                ("PreToolUse", 10),
                            )
                        }
                    }
                )
            )
        self.environment = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def connect(self):
        spawn = subprocess.Popen
        with patch.object(
            HOOK.subprocess,
            "Popen",
            side_effect=lambda args, **kwargs: spawn(
                [
                    arg.replace("features.hooks=false", "features.hooks=true")
                    for arg in args
                ],
                **kwargs,
            ),
        ):
            app = AppServerReader(str(self.root))
        return app

    def discover(self):
        app = self.connect()
        try:
            return app.call(
                "hooks/list", {"cwds": [str(p) for p in self.projects.values()]}, 15
            )["data"]
        finally:
            app.close()
            app.process.stdin.close()
            app.process.stdout.close()

    def test_native_shutdown_releases_cached_deleted_hook(self):
        retired = self.root / "retired-test-handler.py"
        retired.write_text("raise SystemExit(0)\n")
        stop = "import json;print(json.dumps({'decision':'block','reason':'scope-fixture-stop'}))"
        path = self.home / "hooks.json"
        handlers = [
            {"type": "command", "command": shlex.join([sys.executable, str(retired)])},
            {"type": "command", "command": shlex.join([sys.executable, "-c", stop])},
        ]
        path.write_text(
            json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": handlers}]}})
        )
        app = self.connect()
        notifications = []
        read = app.read

        def capture(deadline):
            event = read(deadline)
            notifications.append(event)
            return event

        app.read = capture
        cwd = str(self.projects["unrelated-project"])
        try:
            hooks = app.call("hooks/list", {"cwds": [cwd]}, 15)["data"][0]["hooks"]
            app.call(
                "config/batchWrite",
                {
                    "edits": [
                        {
                            "keyPath": "hooks.state",
                            "mergeStrategy": "replace",
                            "value": {
                                h["key"]: {"trusted_hash": h["currentHash"]}
                                for h in hooks
                            },
                        }
                    ],
                    "reloadUserConfig": True,
                },
                15,
            )
            thread = app.call(
                "thread/start",
                {
                    "cwd": cwd,
                    "model": "gpt-6-luna",
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                },
                15,
            )["thread"]

            def turn():
                notifications.clear()
                response = app.call(
                    "turn/start",
                    {
                        "threadId": thread["id"],
                        "input": [
                            {
                                "type": "text",
                                "text": "scope fixture; hooks stop before inference",
                            }
                        ],
                    },
                    15,
                )
                turn_id = response["turn"]["id"]
                deadline = time.monotonic() + 15
                while not any(
                    e.get("method") == "turn/completed"
                    and e["params"]["turn"]["id"] == turn_id
                    for e in notifications
                ):
                    app.read(deadline)
                self.assertFalse(
                    any(
                        e.get("method") == "item/agentMessage/delta"
                        for e in notifications
                    )
                )
                return [
                    e["params"]["run"]
                    for e in notifications
                    if e.get("method") == "hook/completed"
                ]

            first = turn()
            self.assertFalse(any("No such file" in json.dumps(run) for run in first))
            retired.unlink()
            path.write_text(
                json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": handlers[1:]}]}})
            )
            cached = turn()
            self.assertTrue(any("No such file" in json.dumps(run) for run in cached))
            app.call("thread/archive", {"threadId": thread["id"]}, 15)
            app.call("thread/unarchive", {"threadId": thread["id"]}, 15)
            hooks = app.call("hooks/list", {"cwds": [cwd]}, 15)["data"][0]["hooks"]
            app.call(
                "config/batchWrite",
                {
                    "edits": [
                        {
                            "keyPath": "hooks.state",
                            "mergeStrategy": "replace",
                            "value": {
                                h["key"]: {"trusted_hash": h["currentHash"]}
                                for h in hooks
                            },
                        }
                    ],
                    "reloadUserConfig": True,
                },
                15,
            )
            app.call(
                "thread/resume", {"threadId": thread["id"], "excludeTurns": True}, 15
            )
            refreshed = turn()
            self.assertEqual(len(refreshed), 1)
            self.assertNotIn("No such file", json.dumps(refreshed))
            self.assertIn("scope-fixture-stop", json.dumps(refreshed))
        finally:
            app.close()
            app.process.stdin.close()
            app.process.stdout.close()

    def test_native_sources_are_project_local(self):
        for item in self.discover():
            name = Path(item["cwd"]).name
            hooks = item["hooks"]
            self.assertEqual(item.get("errors", []), [])
            self.assertEqual(len(hooks), 0 if name == "unrelated-project" else 2)
            for hook in hooks:
                self.assertTrue(
                    hook["key"].startswith(
                        str(self.projects[name] / ".codex/hooks.json")
                    )
                )
                self.assertIn(f"MODEL_FIT_AUTO_THREAD={name}-thread ", hook["command"])

    def test_other_threads_in_selected_projects_have_no_side_effects(self):
        for name in ("first-project", "second-project"):
            hooks = json.loads((self.projects[name] / ".codex/hooks.json").read_text())[
                "hooks"
            ]
            for event, groups in hooks.items():
                result = subprocess.run(
                    groups[0]["hooks"][0]["command"],
                    shell=True,
                    capture_output=True,
                    text=True,
                    input=json.dumps(
                        {"session_id": "unrelated-thread", "hook_event_name": event}
                    ),
                    timeout=10,
                )
                self.assertEqual(
                    (result.returncode, result.stdout, result.stderr), (0, "", "")
                )
        self.assertFalse((self.home / ".tmp/model-fit-auto-switch").exists())
        self.assertFalse((self.home / ".tmp/model-fit-hook-audit").exists())

    def test_retired_candidate_worktree_cannot_break_installed_hooks(self):
        repo = self.projects["unrelated-project"]
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "--allow-empty",
                "-qm",
                "fixture",
            ],
            check=True,
            capture_output=True,
        )
        candidate = self.root / "candidate-worktree"
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "worktree",
                "add",
                "--detach",
                str(candidate),
                "HEAD",
            ],
            check=True,
            capture_output=True,
        )
        test_home = self.root / "isolated-test-home"
        test_home.mkdir()
        test_home.joinpath("hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f"python3 {candidate}/deleted.py",
                                    }
                                ]
                            }
                        ]
                    }
                }
            )
        )
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", str(candidate)],
            check=True,
            capture_output=True,
        )
        self.assertFalse(candidate.exists())
        discovered = self.discover()
        self.assertEqual([len(item["hooks"]) for item in discovered], [2, 2, 0])
        state_dir = self.home / ".tmp/model-fit-auto-switch"
        state_dir.mkdir(parents=True)
        for name in ("first-project", "second-project"):
            thread = name + "-thread"
            (state_dir / f"{thread}.json").write_text(
                json.dumps(
                    {
                        "phase": "rejected",
                        "source_turn_id": "control-turn",
                    }
                )
            )
            result = subprocess.run(
                [sys.executable, str(self.handler)],
                capture_output=True,
                text=True,
                timeout=10,
                env=dict(os.environ, MODEL_FIT_AUTO_THREAD=thread),
                input=json.dumps(
                    {
                        "session_id": thread,
                        "turn_id": "control-turn",
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Bash",
                        "tool_input": {"command": "echo should-be-denied"},
                    }
                ),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )


if __name__ == "__main__":
    unittest.main()
