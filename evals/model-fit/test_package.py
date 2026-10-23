"""Verify both Model Fit release variants from their exact archive contents."""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("build", ROOT / "tools/build.py")
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class PackageTests(unittest.TestCase):
    def test_release_rejects_different_variant_versions(self) -> None:
        with patch.object(
            BUILD, "manifest", side_effect=[{"version": "0.1.0"}, {"version": "0.2.0"}]
        ):
            with self.assertRaisesRegex(ValueError, "share one GitHub Release version"):
                BUILD.release_version()

    def test_full_package_contains_runtime_and_guidance_omits_hooks(self) -> None:
        full, full_files = BUILD.full_package()
        guidance, guidance_files = BUILD.guidance_package()
        self.assertEqual(full["name"], "model-fit")
        self.assertEqual(guidance["name"], "model-fit-guidance")
        self.assertEqual(full["version"], BUILD.release_version())
        self.assertEqual(guidance["version"], BUILD.release_version())
        self.assertIn("skills/model-fit/scripts/hook.py", full_files)
        self.assertIn("LICENSE", full_files)
        self.assertIn("skills/model-fit/scripts/triage.py", full_files)
        self.assertNotIn("skills/model-fit/scripts/hook.py", guidance_files)
        self.assertEqual(
            set(guidance_files),
            {
                "plugin.json",
                "README.md",
                "LICENSE",
                "assets/icon.png",
                "skills/model-fit/SKILL.md",
                "skills/model-fit/agents/openai.yaml",
            },
        )
        self.assertNotIn(
            "## Локальный hook", guidance_files["skills/model-fit/SKILL.md"].decode()
        )

    def test_builds_reproducible_single_plugin_archives(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            for identity, files in (BUILD.full_package(), BUILD.guidance_package()):
                one = BUILD.write_archive(identity, files, Path(first))
                two = BUILD.write_archive(identity, files, Path(second))
                self.assertEqual(
                    hashlib.sha256(one.read_bytes()).digest(),
                    hashlib.sha256(two.read_bytes()).digest(),
                )
                with zipfile.ZipFile(one) as archive:
                    self.assertTrue(
                        all(
                            name.startswith(identity["name"] + "/")
                            for name in archive.namelist()
                        )
                    )

    def test_private_absolute_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            (package / "SKILL.md").write_text("source: /Users/person/private")
            with self.assertRaisesRegex(ValueError, "private content"):
                BUILD.source_files(package)


if __name__ == "__main__":
    unittest.main()
