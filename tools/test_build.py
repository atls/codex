import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

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
        self.assertNotIn("src/api.py", cli)
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
