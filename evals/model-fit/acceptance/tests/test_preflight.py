import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "verify.py"
SPEC = importlib.util.spec_from_file_location("media_acceptance_run", PATH)
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


class NativeTrustTests(unittest.TestCase):
    def hooks(self, home, command, trusted=False):
        return [
            {
                "key": str(home / "hooks/hooks.json") + f"#opaque.key[{index}]",
                "eventName": event,
                "handlerType": "command",
                "command": command,
                "sourcePath": str(home / "hooks/hooks.json"),
                "source": "plugin",
                "pluginId": "vector-prime@media-acceptance",
                "currentHash": f"native-hash-{index}",
                "enabled": True,
                "trustStatus": "trusted" if trusted else "untrusted",
            }
            for index, event in enumerate(sorted(RUN.EVENTS))
        ]

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI required")
    def test_installed_capture_hooks_admit_real_dispatcher_without_inference(self):
        with tempfile.TemporaryDirectory() as name:
            home = (Path(name) / "home").resolve()
            home.mkdir()
            workspace = (Path(name) / "work").resolve()
            workspace.mkdir()
            plugin, command = RUN.install_candidate(home, shutil.which("codex"))
            self.assertEqual(
                len(RUN.trust(home, workspace, shutil.which("codex"), command, plugin)),
                3,
            )
            event = {
                "session_id": "fixture-thread",
                "turn_id": "fixture-turn",
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(workspace),
                "model": "gpt-6-luna",
                "prompt": "fixture",
            }
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--quiet",
                    "--project",
                    str(plugin),
                    "python",
                    str(plugin / "scripts/capture_hook.py"),
                    "hook",
                ],
                input=json.dumps(event),
                env=os.environ
                | {"CODEX_HOME": str(home), "CODEX_PLUGIN_ROOT": str(plugin)},
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("hookSpecificOutput", json.loads(result.stdout))
            state = json.loads(
                (home / ".tmp/model-fit-auto-switch/fixture-thread.json").read_text()
            )
            self.assertTrue(state["pending_assessment"])

    def test_trust_writes_one_exact_temporary_file_and_uses_native_opaque_keys_hashes(
        self,
    ):
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            cwd = home / "work"
            cwd.mkdir()
            command = "candidate command"
            calls = []

            class App:
                trusted = False

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    pass

                def call(app, method, params, timeout):
                    calls.append((method, params))
                    if method == "config/batchWrite":
                        app.trusted = True
                        return {}
                    return {
                        "data": [
                            {
                                "hooks": self.hooks(home, command, app.trusted),
                                "errors": [],
                                "warnings": [],
                            }
                        ]
                    }

            first = App()
            second = App()
            second.trusted = True
            with patch.object(RUN, "connect", side_effect=[first, second]):
                result = RUN.trust(home, cwd, "/fixture/codex", command, home)
            writes = [
                params for method, params in calls if method == "config/batchWrite"
            ]
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0]["filePath"], str(home / "config.toml"))
            self.assertEqual(writes[0]["edits"][0]["keyPath"], "hooks.state")
            self.assertEqual(
                writes[0]["edits"][0]["value"],
                {
                    hook["key"]: {"trusted_hash": hook["currentHash"], "enabled": True}
                    for hook in self.hooks(home, command)
                },
            )
            self.assertEqual(len(result), 3)

    def test_unexpected_commands_or_sources_are_not_trusted(self):
        with tempfile.TemporaryDirectory() as name:
            home = Path(name)
            for changed in [
                {"command": "other"},
                {"source": "project"},
                {"sourcePath": "/fixture/other"},
            ]:
                hooks = self.hooks(home, "candidate")
                hooks[0].update(changed)

                class App:
                    def call(self, *args):
                        return {
                            "data": [{"hooks": hooks, "errors": [], "warnings": []}]
                        }

                with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                    RUN.candidate_hooks(App(), home, home, "candidate")

    def test_official_echo_wire_resolves_config_relative_python_grade_without_inference(
        self,
    ):
        import json
        import os
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            manifest = {
                "id": "echo-wire",
                "trustReadbackPassed": True,
                "codex": "codex",
                "home": str(root),
                "workspace": str(root),
                "path": os.environ["PATH"],
                "evidence": str(root),
                "prompt": "fixture",
                "input": [{"type": "text", "text": "fixture"}],
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest))
            config_path = root / "config.json"
            config_path.write_text(json.dumps(RUN.build_config(manifest)))
            result = subprocess.run(
                [
                    "yarn",
                    "exec",
                    "promptfoo",
                    "eval",
                    "--config",
                    str(config_path),
                    "--providers",
                    "echo",
                    "--no-cache",
                    "--max-concurrency",
                    "1",
                    "--output",
                    str(root / "result.json"),
                ],
                cwd=RUN.SUITE,
                env=os.environ
                | {
                    "MODEL_FIT_ACCEPTANCE_MANIFEST": str(path),
                    "PROMPTFOO_PYTHON": sys.executable,
                    "PROMPTFOO_CONFIG_DIR": str(root / "promptfoo"),
                    "PROMPTFOO_DISABLE_TELEMETRY": "1",
                    "LOG_LEVEL": "warn",
                },
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 100, result.stderr)
            grade = json.loads((root / "grade.json").read_text())
            self.assertFalse(grade["pass"])
            self.assertIn(grade["errorType"], {"KeyError", "TypeError"})
            saved = json.loads((root / "result.json").read_text())
            rows = (
                saved["results"]
                if isinstance(saved["results"], list)
                else saved["results"]["results"]
            )
            self.assertEqual(rows[0]["provider"]["id"], "echo")
            self.assertNotIn("error", rows[0]["response"])


class RetainedProviderBridgeTests(unittest.TestCase):
    def test_complete_synthetic_record_passes_real_promptfoo_grade(self):
        import sys
        from fixtures.acceptance.media import media_context

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            context = media_context(root)
            provider = {
                "output": '{"colors":["red","blue"],"imageCount":2}',
                **context["providerResponse"],
            }
            config = {
                "prompts": [json.dumps(provider)],
                "providers": [
                    "file://" + str(PATH.parent / "tests/retained_provider.py")
                ],
                "tests": [
                    {
                        "vars": context["vars"],
                        "assert": [
                            {
                                "type": "python",
                                "value": "file://" + str(PATH.parent / "grade.py"),
                            }
                        ],
                    }
                ],
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config))
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
                    str(root / "result.json"),
                ],
                cwd=RUN.SUITE,
                env=os.environ
                | {
                    "PROMPTFOO_PYTHON": sys.executable,
                    "PROMPTFOO_CONFIG_DIR": str(root / "promptfoo"),
                    "PROMPTFOO_DISABLE_TELEMETRY": "1",
                    "LOG_LEVEL": "warn",
                },
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(
                json.loads((root / "evidence/grade.json").read_text())["pass"]
            )

    def test_source_failure_control_does_not_require_an_upstream_bug(self):
        from unittest.mock import MagicMock

        for unsupported in (False, True):
            owner, reader = MagicMock(), MagicMock()
            owner.__enter__.return_value.call.return_value = {"thread": {"id": "probe"}}
            if unsupported:
                reader.__enter__.return_value.call.side_effect = RUN.AppServerRPCError(
                    "thread not loaded: probe",
                    method="thread/read",
                    code=-32600,
                    thread_id="probe",
                )
            else:
                reader.__enter__.return_value.call.return_value = {"data": []}
            with (
                self.subTest(unsupported=unsupported),
                patch.object(RUN, "connect", side_effect=[owner, reader]),
            ):
                result = RUN.capability_preflight(
                    Path("/fixture"), Path("/fixture/work"), "codex"
                )
            self.assertIs(result["zeroTurnControl"], unsupported)


class InapplicableControlTests(unittest.TestCase):
    def test_absent_failure_boundary_does_not_start_model_rows_or_claim_pass(self):
        import sys

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "source-home"
            source.mkdir()
            original = '{"auth_mode":"chatgpt","fixture":true}'
            (source / "auth.json").write_text(original)
            evidence = root / "evidence"
            env = {
                "CODEX_EVAL_HOME": str(source),
                "MODEL_FIT_IMAGE_PYTHON": sys.executable,
                "MODEL_FIT_ACCEPTANCE_OUTPUT": str(evidence),
                "MODEL_FIT_ACCEPTANCE_ROWS": "text-two-images,empty-two-images",
            }
            with (
                patch.dict(os.environ, env),
                patch.object(RUN.shutil, "which", return_value=sys.executable),
                patch.object(
                    RUN,
                    "install_candidate",
                    return_value=(root / "plugin", "fixture-command"),
                ),
                patch.object(RUN, "trust", return_value=[]),
                patch.object(
                    RUN, "capability_preflight", return_value={"zeroTurnControl": False}
                ),
                patch.object(
                    RUN,
                    "build_config",
                    side_effect=AssertionError("Model evaluation was constructed"),
                ),
            ):
                RUN.main()
            report = json.loads((evidence / "safe-report.json").read_text())
            self.assertEqual(report["status"], "not_applicable")
            self.assertEqual(report["completedRows"], 0)
            self.assertTrue(report["rows"])
            self.assertTrue(
                all(
                    row["pass"] is None and row["status"] == "not_applicable"
                    for row in report["rows"]
                )
            )
            self.assertEqual((source / "auth.json").read_text(), original)
