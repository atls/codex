import json
import unittest
from importlib.resources import files

from jsonschema import Draft202012Validator


class DecisionSchemaTests(unittest.TestCase):
    def test_generated_schema_preserves_the_public_decision_contract(self):
        schema = json.loads(
            files("model_fit.application.assessment")
            .joinpath("decision.schema.json")
            .read_text()
        )
        Draft202012Validator.check_schema(schema)
        expected_fields = {
            "active_model",
            "active_effort",
            "active_speed",
            "decision",
            "recommended_model",
            "recommended_effort",
            "recommended_speed",
            "official_source_url",
            "official_guidance",
            "task_inference",
            "reason",
        }
        self.assertEqual(set(schema["properties"]), expected_fields)
        self.assertEqual(set(schema["required"]), expected_fields)
        validator = Draft202012Validator(schema)
        decision = {
            "active_model": "fixture-model",
            "active_effort": "medium",
            "active_speed": None,
            "decision": "keep",
            "recommended_model": None,
            "recommended_effort": None,
            "recommended_speed": None,
            "official_source_url": None,
            "official_guidance": None,
            "task_inference": None,
            "reason": "Explicitly retained fixture profile",
        }
        self.assertTrue(validator.is_valid(decision))
        self.assertFalse(validator.is_valid({**decision, "work_relation": "execution"}))
        self.assertFalse(validator.is_valid({**decision, "active_model": False}))
        self.assertFalse(validator.is_valid({**decision, "decision": "fixture-value"}))
        incomplete = dict(decision)
        incomplete.pop("reason")
        self.assertFalse(validator.is_valid(incomplete))
