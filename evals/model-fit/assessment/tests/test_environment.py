import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE))
from configuration import build_suite, suite_cases
from evaluate import absolute_references
from infrastructure.adapters.codex.session import evaluation_session


class EvaluationEnvironmentTests(unittest.TestCase):
    def test_explicit_login_is_copied_privately_and_resources_are_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "selected"
            source.mkdir()
            active = Path(directory) / "active"
            active.mkdir()
            original = '{"auth_mode":"chatgpt","fixture":"selected"}'
            (source / "auth.json").write_text(original)
            (active / "auth.json").write_text('{"fixture":"wrong account"}')
            with patch.dict(
                os.environ,
                {
                    "CODEX_EVAL_HOME": str(source),
                    "CODEX_HOME": str(active),
                    "CODEX_PATH": sys.executable,
                },
            ):
                with evaluation_session(
                    [{"id": "case"}], install_skill=False
                ) as runtime:
                    home = Path(runtime["config"]["cli_env"]["CODEX_HOME"])
                    workspace = Path(runtime["workspaces"]["case"])
                    copy = home / "auth.json"
                    self.assertEqual(copy.read_text(), original)
                    self.assertFalse(copy.is_symlink())
                    self.assertNotEqual(
                        copy.stat().st_ino, (source / "auth.json").stat().st_ino
                    )
                    self.assertEqual(copy.stat().st_mode & 511, 384)
                    copy.write_text("provider changed its private copy")
                    self.assertEqual((source / "auth.json").read_text(), original)
                    self.assertTrue((workspace / ".git").exists())
                    self.assertFalse(
                        runtime["config"]["cli_config"]["allow_login_shell"]
                    )
                    self.assertEqual(
                        set(runtime["config"]["cli_config"]["features"].values()),
                        {False},
                    )
                self.assertFalse(home.exists())
                self.assertFalse(workspace.exists())

    def test_workspace_ids_cannot_escape_the_owned_root(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "auth.json").write_text('{"auth_mode":"chatgpt"}')
            with patch.dict(
                os.environ, {"CODEX_EVAL_HOME": str(home), "CODEX_PATH": sys.executable}
            ):
                for identifier in ["../outside", "/outside", ".."]:
                    with (
                        self.subTest(identifier=identifier),
                        self.assertRaises(ValueError),
                    ):
                        with evaluation_session([{"id": identifier}]):
                            self.fail("Unsafe workspace accepted")

    def test_python_suites_preserve_selection_and_native_provider_interfaces(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "auth.json").write_text('{"auth_mode":"chatgpt"}')
            with patch.dict(
                os.environ, {"CODEX_EVAL_HOME": str(home), "CODEX_PATH": sys.executable}
            ):
                for surface, count in [
                    ("native", 26),
                    ("assessment", 28),
                    ("ordinary", 1),
                    ("calibration", 25),
                ]:
                    with (
                        self.subTest(surface=surface),
                        evaluation_session([{"id": "generated-tests"}]) as runtime,
                    ):
                        config = absolute_references(build_suite(surface, runtime))
                        self.assertEqual(len(config["tests"]), count)
                        paths = [
                            entry["vars"]["workspace"] for entry in config["tests"]
                        ]
                        self.assertEqual(len(set(paths)), count)
                        self.assertTrue(
                            all(
                                (
                                    Path(path).is_relative_to(runtime["root"])
                                    for path in paths
                                )
                            )
                        )
                        if surface == "assessment":
                            self.assertEqual(
                                config["providers"][0]["env"]["CODEX_HOME"],
                                runtime["config"]["cli_env"]["CODEX_HOME"],
                            )
                        for entry in config["tests"]:
                            for assertion in entry["assert"]:
                                if assertion.get("type") == "python":
                                    self.assertTrue(
                                        assertion["value"].startswith("file:///")
                                    )

    def test_native_file_references_are_absolute_without_rewriting_vendor_ids(self):
        result = absolute_references(
            {
                "providers": ["openai:codex-app-server"],
                "assert": [
                    {"value": "file://autoswitch/execution/assertions.py:get_assert"}
                ],
            }
        )
        self.assertEqual(result["providers"], ["openai:codex-app-server"])
        self.assertEqual(
            result["assert"][0]["value"],
            "file://"
            + str(SUITE / "autoswitch/execution/assertions.py")
            + ":get_assert",
        )

    def test_api_key_login_is_rejected_before_any_provider_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "auth.json").write_text('{"auth_mode":"apikey"}')
            with (
                patch.dict(os.environ, {"CODEX_EVAL_HOME": str(home)}),
                self.assertRaisesRegex(ValueError, "ChatGPT login"),
            ):
                with evaluation_session([]):
                    self.fail("API-key account accepted for a subscription evaluation")

    def test_fixed_tasks_preserve_provider_labels_without_installing_selection_skill(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "auth.json").write_text('{"auth_mode":"chatgpt"}')
            with patch.dict(
                os.environ, {"CODEX_EVAL_HOME": str(home), "CODEX_PATH": sys.executable}
            ):
                with evaluation_session(
                    suite_cases("tasks"), install_skill=False
                ) as runtime:
                    config = build_suite("tasks", runtime)
                    self.assertEqual(
                        [provider["label"] for provider in config["providers"]],
                        ["current-sol-medium", "candidate-luna-low"],
                    )
                    self.assertEqual(len(config["tests"]), 3)
                    self.assertIsNone(runtime["skill"])
