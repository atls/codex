import json
from pathlib import Path
import tempfile
import unittest

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
            (root / FIXTURES[0]).write_text(
                json.dumps({"value": "data:image/png;base64,fixture"})
            )
            with self.assertRaises(ValueError):
                validate_fixtures(root)
            (root / FIXTURES[0]).write_text("invalid json")
            with self.assertRaises(json.JSONDecodeError):
                validate_fixtures(root)
