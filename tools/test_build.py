import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("package_build", ROOT / "tools/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class DistributionTests(unittest.TestCase):
    def test_variants_share_assessor_and_exclude_development_files(self):
        _, full = build.full_package()
        _, cli = build.guidance_package()
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
                        "src/model_fit/application/answer/",
                        "src/model_fit/entrypoints/hooks/",
                    )
                )
                for name in cli
            )
        )
        metadata = json.loads(cli["plugin.json"])
        extension = metadata["extensions"]["com.openai"]
        self.assertTrue(extension["requires_local_executor"])
        self.assertNotIn("hooks", metadata)
        self.assertNotIn("hooks", extension)
        self.assertNotIn(".app.json", cli)
        self.assertIsNone(metadata.get("apps"))
        self.assertIsNone(extension.get("apps"))
        for files in (full, cli):
            self.assertFalse(
                any("tests/" in name or name.startswith("evals/") for name in files)
            )

    def test_both_archives_build_without_evaluation_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(
                ROOT / "plugins",
                root / "plugins",
                ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info"),
            )
            shutil.copy(ROOT / "LICENSE", root / "LICENSE")
            (root / "tools").mkdir()
            shutil.copy(ROOT / "tools/build.py", root / "tools/build.py")
            self.assertFalse((root / "evals").exists())
            result = subprocess.run(
                [sys.executable, str(root / "tools/build.py")],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list((root / "dist").glob("*.zip"))), 2)

    def test_clean_cli_install_without_hooks_or_submission_state(self):
        identity, files = build.guidance_package()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = build.write_archive(identity, files, root)
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(root / "installed")
            package = root / "installed" / identity["name"]
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


if __name__ == "__main__":
    unittest.main()


class SourceBoundaryTests(unittest.TestCase):
    def test_assembly_rejects_private_text_and_symlink_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "package"
            package.mkdir()
            note = package / "note.md"
            note.write_text("Private local path: /Users/synthetic/private.json")
            with self.assertRaises(ValueError):
                build.source_files(package)
            note.unlink()
            outside = root / "outside.txt"
            outside.write_text("outside the distribution source")
            (package / "linked.txt").symlink_to(outside)
            with self.assertRaises(ValueError):
                build.source_files(package)
