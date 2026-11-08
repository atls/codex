import importlib.util
import sys
from pathlib import Path


import os
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "plugins/model-fit/src"


def load(name, path):
    spec = importlib.util.spec_from_file_location("model_fit." + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AuthIsolationTests(unittest.TestCase):
    def test_app_servers_can_replace_private_auth_without_changing_login(self):
        for name, path in (
            (
                "isolation_triage",
                SCRIPTS
                / "infrastructure/adapters/codex/transport/assessment/session.py",
            ),
        ):
            module = load(name, path)
            with self.subTest(runtime=name), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                source = home / "auth.json"
                source.write_text('{"auth_mode":"chatgpt","fixture":true}')
                original = source.read_bytes()
                with (
                    patch.dict(os.environ, {"CODEX_HOME": str(home)}),
                    patch.object(module.subprocess, "Popen"),
                    patch.object(module.AppServer, "call", return_value={}),
                    patch.object(module.AppServer, "send"),
                ):
                    app = module.AppServer(
                        home,
                        ROOT / "plugins/model-fit/skills/model-fit",
                        home / "stderr.log",
                    )
                    try:
                        isolated = Path(app.home.name) / "auth.json"
                        self.assertFalse(isolated.is_symlink())
                        self.assertEqual(stat.S_IMODE(isolated.stat().st_mode), 0o600)
                        isolated.write_text('{"auth_mode":"fixture-replacement"}')
                        self.assertEqual(source.read_bytes(), original)
                    finally:
                        app.stderr.close()
                        app.home.cleanup()

    def test_relevance_evaluator_cannot_write_through_to_login(self):
        module = load(
            "isolation_replay",
            SCRIPTS / "../src/infrastructure/adapters/codex/answer.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / "auth.json"
            source.write_text('{"auth_mode":"chatgpt","fixture":true}')
            original = source.read_bytes()

            def execute(command, **kwargs):
                isolated = Path(kwargs["env"]["CODEX_HOME"]) / "auth.json"
                self.assertFalse(isolated.is_symlink())
                self.assertEqual(stat.S_IMODE(isolated.stat().st_mode), 0o600)
                isolated.write_text('{"auth_mode":"fixture-replacement"}')
                Path(command[command.index("--output-last-message") + 1]).write_text(
                    '{"verdict":"relevant"}'
                )
                return module.subprocess.CompletedProcess(command, 0, stdout="")

            with (
                patch.dict(os.environ, {"CODEX_HOME": str(home)}),
                patch.object(module.subprocess, "run", side_effect=execute),
            ):
                self.assertEqual(
                    module.classify_answer("request", "context", "answer"), "relevant"
                )
            self.assertEqual(source.read_bytes(), original)

    def test_shared_home_cleans_up_on_exit_and_failed_copy(self):
        from model_fit.infrastructure.adapters.codex import authentication as runtime

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / "auth.json"
            source.write_text('{"auth_mode":"chatgpt","fixture":true}')
            before = source.stat()
            with patch.dict(os.environ, {"CODEX_HOME": str(home)}):
                with runtime.authenticated_home("model-fit-test-") as name:
                    isolated = Path(name)
                    copy = isolated / "auth.json"
                    self.assertNotEqual(copy.stat().st_ino, source.stat().st_ino)
                    copy.write_text("changed")
                self.assertFalse(isolated.exists())
                self.assertEqual(source.stat().st_mtime_ns, before.st_mtime_ns)
                created = runtime.tempfile.TemporaryDirectory(dir=directory)
                with (
                    patch.object(
                        runtime.tempfile, "TemporaryDirectory", return_value=created
                    ),
                    patch.object(
                        runtime.shutil,
                        "copyfile",
                        side_effect=OSError("fixture copy failure"),
                    ),
                ):
                    with self.assertRaises(OSError):
                        runtime.authenticated_home("unused")
                self.assertFalse(Path(created.name).exists())

    def test_isolated_evaluator_spawn_and_initialize_failure_release_private_home(self):
        from model_fit.infrastructure.adapters.codex import authentication as runtime

        module = load(
            "isolation_triage_failure",
            SCRIPTS / "infrastructure/adapters/codex/transport/assessment/session.py",
        )
        for stage in ("spawn", "initialize"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                (home / "auth.json").write_text(
                    '{"auth_mode":"chatgpt","fixture":true}'
                )
                created = []

                def prepare(prefix):
                    temporary = runtime.authenticated_home(prefix)
                    created.append(temporary.name)
                    return temporary

                with (
                    patch.dict(os.environ, {"CODEX_HOME": str(home)}),
                    patch.object(module, "authenticated_home", side_effect=prepare),
                    patch.object(
                        module.subprocess,
                        "Popen",
                        side_effect=OSError("spawn") if stage == "spawn" else None,
                    ),
                    patch.object(
                        module.AppServer, "call", side_effect=RuntimeError("initialize")
                    ),
                ):
                    with self.assertRaises((OSError, RuntimeError)):
                        module.AppServer(
                            home, ROOT / "plugins/model-fit/skills/model-fit"
                        )
                self.assertEqual(len(created), 1)
                self.assertFalse(Path(created[0]).exists())

    def test_isolated_app_server_explicitly_disables_hooks_plugins_apps_and_snapshots(
        self,
    ):
        module = load(
            "isolation_flags_triage",
            SCRIPTS / "infrastructure/adapters/codex/transport/assessment/session.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "auth.json").write_text('{"auth_mode":"chatgpt","fixture":true}')
            with (
                patch.dict(os.environ, {"CODEX_HOME": str(home)}),
                patch.object(module.subprocess, "Popen") as spawn,
                patch.object(module.AppServer, "call", return_value={}),
                patch.object(module.AppServer, "send"),
            ):
                with module.AppServer(
                    home, ROOT / "plugins/model-fit/skills/model-fit"
                ):
                    command = spawn.call_args.args[0]
                    for flag in [
                        "features.hooks=false",
                        "features.plugins=false",
                        "features.apps=false",
                        "features.shell_snapshot=false",
                    ]:
                        self.assertIn(flag, command)
