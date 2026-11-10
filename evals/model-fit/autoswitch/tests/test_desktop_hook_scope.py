"""Native hook discovery and process isolation without inference requests."""

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "plugins/model-fit/src/model_fit"
from model_fit.entrypoints.hooks import prompt as HOOK


@unittest.skipUnless(shutil.which("codex"), "Installed Codex app-server is required")
class DesktopHookScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="model-fit-scope-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "codex-home"
        self.home.mkdir()
        self.plugin = self.home / "plugins/model-fit"
        self.handler = self.plugin / "src/model_fit/entrypoints/hooks/cli.py"
        shutil.copytree(
            SCRIPTS.parent,
            self.plugin,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"),
        )
        self.projects = {}
        for name in ("first-project", "second-project", "unrelated-project"):
            repo = self.root / name
            repo.mkdir()
            subprocess.run(
                ["git", "init", "-q", str(repo)], check=True, capture_output=True
            )
            self.projects[name] = repo
        self.home.joinpath("config.toml").write_text(
            "[features]\nplugin_discovery_prefetch = false\n"
            + "\n".join(
                (
                    f'[projects.{json.dumps(str(repo))}]\ntrust_level = "trusted"\n'
                    for repo in self.projects.values()
                )
            )
        )
        for name in ("first-project", "second-project"):
            path = self.projects[name] / ".codex/hooks.json"
            path.parent.mkdir()
            command = f"MODEL_FIT_AUTO_THREAD={name}-thread uv run --quiet --project {shlex.quote(str(self.plugin))} python -m model_fit.entrypoints.hooks.cli lifecycle"
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
            from model_fit.infrastructure.adapters.codex.history import AppServerReader

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


if __name__ == "__main__":
    unittest.main()
