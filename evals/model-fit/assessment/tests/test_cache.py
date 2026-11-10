import json
import tempfile
import unittest
from pathlib import Path

from model_fit.infrastructure.adapters.filesystem.assessment_cache import (
    FileAssessmentCache,
)


class AssessmentCacheTests(unittest.TestCase):
    def test_legacy_evidence_preserves_absence_and_ignores_unknown_nested_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cached.json"
            profile = {"model": "fixture-model", "effort": "low", "speed": None}
            path.write_text(
                json.dumps(
                    {
                        "prompt_hash": "a" * 64,
                        "active_profile": {**profile, "future_profile_metadata": True},
                        "result": {
                            "decision": "recommend_lighter",
                            "official_source_url": None,
                            "future_evidence": {"fixture": True},
                        },
                    }
                )
            )
            original = path.read_bytes()
            cache = FileAssessmentCache(lambda _: path)
            self.assertEqual(
                cache.load("fixture-thread"),
                {
                    "prompt_hash": "a" * 64,
                    "active_profile": profile,
                    "result": {
                        "decision": "recommend_lighter",
                        "official_source_url": None,
                    },
                },
            )
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_known_evidence_does_not_become_a_usable_cached_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cached.json"
            path.write_text(
                json.dumps(
                    {
                        "prompt_hash": "a" * 64,
                        "active_profile": {
                            "model": "fixture-model",
                            "effort": "low",
                            "speed": None,
                        },
                        "result": {"decision": "recommend_lighter", "reason": False},
                    }
                )
            )
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                FileAssessmentCache(lambda _: path).load("fixture-thread")
            self.assertEqual(path.read_bytes(), original)
