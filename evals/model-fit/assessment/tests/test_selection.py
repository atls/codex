import unittest

from assessment.selection import get_assert


class ControllerEvidenceTests(unittest.TestCase):
    def check(self, scenario, metadata):
        return get_assert(
            "",
            {
                "vars": {"scenario": scenario},
                "providerResponse": {"metadata": metadata},
            },
        )["pass"]

    def test_native_model_turn_and_skill_evidence_are_both_required(self):
        self.assertFalse(self.check({}, {"skill_item_seen": True, "model_turns": 0}))
        self.assertTrue(self.check({}, {"skill_item_seen": True, "model_turns": 1}))
        self.assertFalse(self.check({}, {"skill_item_seen": False, "model_turns": 1}))
        self.assertFalse(self.check({}, {"skill_item_seen": True, "model_turns": True}))

    def test_source_failure_and_user_choice_need_explicit_zero_turn_evidence(self):
        for scenario, flag in [
            ({"source_failure": "catalog"}, "source_failure_simulation"),
            ({"prior_choice": True}, "user_choice_bypass"),
        ]:
            self.assertTrue(self.check(scenario, {flag: True, "model_turns": 0}))
            self.assertFalse(self.check(scenario, {flag: True, "model_turns": False}))
            self.assertFalse(self.check(scenario, {flag: True, "model_turns": 1}))
            self.assertFalse(self.check(scenario, {"model_turns": 0}))

    def test_missing_or_invalid_metadata_is_fail_not_exception(self):
        for context in [
            {},
            {"vars": {"scenario": {}}},
            {"vars": {"scenario": {}}, "providerResponse": {}},
            {"vars": {"scenario": {}}, "providerResponse": {"metadata": []}},
        ]:
            self.assertFalse(get_assert("", context)["pass"])
