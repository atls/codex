"""Verify native project hook setup without touching a live Codex project."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins/model-fit/skills/model-fit/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("configure", SCRIPTS / "configure.py")
CONFIGURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIGURE)


class ConfigureTests(unittest.TestCase):
    thread_id = "test-thread"

    def test_adds_three_hooks_and_preserves_unrelated_handlers(self) -> None:
        original = {
            "description": "Existing project hooks",
            "hooks": {
                "PostToolUse": [
                    {"hooks": [{"type": "command", "command": "echo existing"}]}
                ],
            },
        }
        result = CONFIGURE.configure(original, self.thread_id)
        self.assertEqual(result["description"], original["description"])
        self.assertEqual(
            result["hooks"]["PostToolUse"], original["hooks"]["PostToolUse"]
        )
        self.assertEqual(
            set(CONFIGURE.EVENT_TIMEOUTS) | {"PostToolUse"}, set(result["hooks"])
        )
        for event, timeout in CONFIGURE.EVENT_TIMEOUTS.items():
            handler = result["hooks"][event][0]["hooks"][0]
            self.assertEqual(handler["timeout"], timeout)
            self.assertIn("MODEL_FIT_AUTO_THREAD=test-thread", handler["command"])
        self.assertEqual(CONFIGURE.configure(result, self.thread_id), result)
        self.assertEqual(original["hooks"].keys(), {"PostToolUse"})

    def test_removal_keeps_unrelated_hooks(self) -> None:
        original = {
            "hooks": {
                "PreToolUse": [
                    {"hooks": [{"type": "command", "command": "echo existing"}]}
                ]
            }
        }
        configured = CONFIGURE.configure(original, self.thread_id)
        removed = CONFIGURE.configure(configured, self.thread_id, remove=True)
        self.assertEqual(
            removed["hooks"]["PreToolUse"], original["hooks"]["PreToolUse"]
        )
        self.assertFalse(removed["hooks"]["UserPromptSubmit"])
        self.assertFalse(removed["hooks"]["Stop"])

    def test_conflicting_definition_is_rejected(self) -> None:
        existing = {
            "hooks": {
                "PreToolUse": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "MODEL_FIT_AUTO_THREAD=test-thread python3 /temporary/hook.py",
                                "timeout": 10,
                            }
                        ]
                    }
                ]
            }
        }
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            CONFIGURE.configure(existing, self.thread_id)

    def test_dry_run_and_write_have_exact_readback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            output = io.StringIO()
            with (
                patch(
                    "sys.argv",
                    [
                        "configure.py",
                        "--project",
                        directory,
                        "--thread-id",
                        self.thread_id,
                    ],
                ),
                redirect_stdout(output),
            ):
                self.assertEqual(CONFIGURE.main(), 0)
            self.assertFalse((project / ".codex/hooks.json").exists())
            with (
                patch(
                    "sys.argv",
                    [
                        "configure.py",
                        "--project",
                        directory,
                        "--thread-id",
                        self.thread_id,
                        "--write",
                    ],
                ),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(CONFIGURE.main(), 0)
            data = json.loads((project / ".codex/hooks.json").read_text())
            self.assertEqual(
                data,
                CONFIGURE.configure(
                    CONFIGURE.load_hooks(project / ".codex/hooks.json"), self.thread_id
                ),
            )
            self.assertEqual(
                (project / ".codex/hooks.json").stat().st_mode & 0o777, 0o600
            )

    def test_symlinked_hooks_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = project / "target.json"
            target.write_text('{"hooks": {}}')
            (project / ".codex").mkdir()
            (project / ".codex/hooks.json").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                CONFIGURE.load_hooks(project / ".codex/hooks.json")

    def test_git_project_keeps_thread_id_out_of_tracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            CONFIGURE.ensure_local_exclude(project)
            CONFIGURE.save(
                project / ".codex/hooks.json",
                CONFIGURE.configure(
                    CONFIGURE.load_hooks(project / ".codex/hooks.json"),
                    self.thread_id,
                ),
            )
            ignored = subprocess.run(
                ["git", "-C", directory, "check-ignore", "-q", ".codex/hooks.json"],
            )
            self.assertEqual(ignored.returncode, 0)
            self.assertEqual(
                (project / ".git/info/exclude").read_text().count("/.codex/hooks.json"),
                1,
            )
            CONFIGURE.ensure_local_exclude(project)
            self.assertEqual(
                (project / ".git/info/exclude").read_text().count("/.codex/hooks.json"),
                1,
            )

    def test_tracked_hooks_file_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            (project / ".codex").mkdir()
            (project / ".codex/hooks.json").write_text('{"hooks": {}}')
            subprocess.run(
                ["git", "-C", directory, "add", ".codex/hooks.json"], check=True
            )
            with self.assertRaisesRegex(ValueError, "tracked"):
                CONFIGURE.ensure_local_exclude(project)


if __name__ == "__main__":
    unittest.main()
