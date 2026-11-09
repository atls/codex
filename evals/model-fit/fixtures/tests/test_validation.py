import json
import tempfile
import unittest
from pathlib import Path

from fixtures.validation import FIXTURES, validate_fixtures


class PublicFixtureTests(unittest.TestCase):
    def test_valid_public_data_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in FIXTURES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]")
            validate_fixtures(root)
            for private in (
                "data:image/png;base64,fixture",
                "/Users/synthetic/private.json",
                "codex://threads/synthetic",
                "-----BEGIN PRIVATE KEY-----synthetic",
            ):
                with self.subTest(private=private):
                    (root / FIXTURES[0]).write_text(json.dumps({"value": private}))
                    with self.assertRaises(ValueError):
                        validate_fixtures(root)
            (root / FIXTURES[0]).write_text("invalid json")
            with self.assertRaises(json.JSONDecodeError):
                validate_fixtures(root)
