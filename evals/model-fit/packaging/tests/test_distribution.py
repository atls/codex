import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(
            ROOT / "plugins",
            self.root / "plugins",
            ignore=shutil.ignore_patterns(
                ".venv", "__pycache__", "build", "dist", "*.egg-info"
            ),
        )
        shutil.copytree(ROOT / ".github/packaging", self.root / ".github/packaging")
        shutil.copy(ROOT / "LICENSE", self.root / "LICENSE")
        definition = yaml.safe_load(
            (ROOT / ".github/actions/package/action.yml").read_text()
        )
        self.command = definition["runs"]["steps"][0]["run"]
        self.environment = {**os.environ, "PACKAGE_OUTPUT": str(self.root / "dist")}
        self.build()
        self.archives = {
            name: next((self.root / "dist").glob(name + "-[0-9]*.zip"))
            for name in ("model-fit", "model-fit-guidance")
        }

    def build(self):
        result = subprocess.run(
            ["bash", "-e", "-c", self.command],
            cwd=self.root,
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_variants_share_assessor_and_exclude_development_files(self):
        self.assertFalse((self.root / "evals").exists())
        contents = {}
        for name, archive in self.archives.items():
            with zipfile.ZipFile(archive) as package:
                contents[name] = {
                    member[len(name) + 1 :]: package.read(member)
                    for member in package.namelist()
                    if not member.endswith("/")
                }
        full, cli = contents["model-fit"], contents["model-fit-guidance"]
        for name, content in cli.items():
            if name.startswith("src/"):
                self.assertEqual(content, full[name], name)
        self.assertIn("hooks/hooks.json", full)
        self.assertNotIn("hooks/hooks.json", cli)
        self.assertIn("src/model_fit/application/assessment/lifecycle.py", cli)
        self.assertFalse(
            any(
                name.startswith(
                    (
                        "src/model_fit/application/switch/",
                        "src/model_fit/application/handoff/",
                        "src/model_fit/entrypoints/hooks/",
                    )
                )
                for name in cli
            )
        )
        for files in (full, cli):
            self.assertFalse(
                any("tests/" in name or name.startswith("evals/") for name in files)
            )
        metadata = json.loads(cli["plugin.json"])
        self.assertTrue(metadata["extensions"]["com.openai"]["requires_local_executor"])
        self.assertNotIn("hooks", metadata)
        self.assertNotIn("hooks", metadata["extensions"]["com.openai"])

    def test_unlisted_files_stay_out_and_selected_symlinks_fail(self):
        source = self.root / "plugins/model-fit"
        (source / "private-fixture.json").write_text('{"fixture":true}')
        self.build()
        with zipfile.ZipFile(self.archives["model-fit"]) as package:
            self.assertNotIn("model-fit/private-fixture.json", package.namelist())
        (source / "src/model_fit/linked.py").symlink_to(source / "private-fixture.json")
        result = subprocess.run(
            ["bash", "-e", "-c", self.command],
            cwd=self.root,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_clean_cli_install_without_hooks_or_submission_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.archives["model-fit-guidance"]
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(root / "installed")
            package = root / "installed" / "model-fit-guidance"
            home = root / "codex-home"
            home.mkdir()
            (home / "config.toml").write_text(
                "[features]\nhooks=false\nplugins=false\n"
            )
            env = {**os.environ, "CODEX_HOME": str(home)}
            env.pop("PYTHONPATH", None)
            profile = {"model": "gpt-6-luna", "effort": "low", "speed": None}
            request = {
                "task": "Keep my selected profile",
                "active_profile": profile,
                "prior_choice": {
                    "user_selected": True,
                    "same_work": True,
                    "profile": profile,
                },
            }
            command = [
                "uv",
                "run",
                "--locked",
                "--project",
                str(package),
                "--python",
                sys.executable,
                "model-fit",
            ]
            result = subprocess.run(
                command,
                input=json.dumps(request),
                text=True,
                capture_output=True,
                env=env,
                cwd=root,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["decision"], "keep")
            self.assertFalse((home / ".tmp").exists())
            malformed = subprocess.run(
                command,
                input="{}",
                text=True,
                capture_output=True,
                env=env,
                cwd=root,
                timeout=30,
            )
            self.assertEqual(malformed.returncode, 2)
            self.assertEqual(malformed.stdout, "")

    def test_noneditable_evaluator_uses_installed_skill_after_source_removal(self):
        for name, archive in self.archives.items():
            with (
                self.subTest(distribution=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                with zipfile.ZipFile(archive) as zipped:
                    zipped.extractall(root)
                package = root / name
                home = root / "home"
                home.mkdir()
                (home / "auth.json").write_text('{"fixture":true}')
                command = [
                    "uv",
                    "run",
                    "--locked",
                    "--no-editable",
                    "--project",
                    str(package),
                    "--python",
                    sys.executable,
                    "python",
                    "-c",
                    """
import sys
from pathlib import Path
from unittest.mock import patch
from model_fit.infrastructure.adapters.codex.transport.assessment import session

source = Path(sys.argv[1])
expected = (source / "skills/model-fit/references/assessment-policy.md").read_bytes()
(source / "skills").rename(source / "removed-skills")
(source / "src").rename(source / "removed-src")
with patch.object(session.subprocess, "Popen"), patch.object(session.AppServer, "call", return_value={}), patch.object(session.AppServer, "send"):
    with session.AppServer(source) as app:
        assert app.skill_file.is_file()
        assert (app.skill_file.parent / "references/assessment-policy.md").read_bytes() == expected
print("installed evaluator skill available without source")
""",
                    str(package),
                ]
                result = subprocess.run(
                    command,
                    cwd=root,
                    env={**os.environ, "CODEX_HOME": str(home)},
                    text=True,
                    capture_output=True,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    "installed evaluator skill available without source", result.stdout
                )
