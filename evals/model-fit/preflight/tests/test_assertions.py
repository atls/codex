import json
import unittest

from preflight.assertions import get_assert


class SkillInputTests(unittest.TestCase):
    def context(self, content=None):
        return {
            "vars": {"skill_file": "/fixture/SKILL.md"},
            "providerResponse": {
                "raw": json.dumps(
                    {"items": [{"type": "user_message", "content": content or []}]}
                )
            },
        }

    def test_native_skill_input_is_required_not_configuration_alone(self):
        self.assertFalse(get_assert("", self.context())["pass"])
        content = [{"type": "skill", "name": "model-fit", "path": "/fixture/SKILL.md"}]
        self.assertTrue(get_assert("", self.context(content))["pass"])

    def test_different_path_or_skill_and_malformed_trace_cannot_confirm_activation(
        self,
    ):
        for content in [
            [{"type": "skill", "name": "model-fit", "path": "/other/SKILL.md"}],
            [{"type": "skill", "name": "other", "path": "/fixture/SKILL.md"}],
        ]:
            self.assertFalse(get_assert("", self.context(content))["pass"])
        for context in [
            {},
            {"providerResponse": {}},
            {"vars": {}, "providerResponse": {"raw": "invalid"}},
            {
                "vars": {"skill_file": "/fixture/SKILL.md"},
                "providerResponse": {"raw": "null"},
            },
        ]:
            self.assertFalse(get_assert("", context)["pass"])
