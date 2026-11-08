import json
import unittest

from assessment.ordinary.assertions import get_assert


class OrdinaryDialogueTests(unittest.TestCase):
    def context(self, items):
        return {"providerResponse": {"raw": json.dumps({"items": items})}}

    def test_normal_dialogue_with_only_messages_and_reasoning_passes(self):
        self.assertTrue(
            get_assert(
                "git status --short shows changed files",
                self.context([{"type": "agent_message"}, {"type": "reasoning"}]),
            )["pass"]
        )

    def test_tools_or_profile_advice_fail(self):
        self.assertFalse(
            get_assert("answer", self.context([{"type": "command_execution"}]))["pass"]
        )
        for answer in [
            "Use model-fit",
            "gpt-6-luna",
            "LUNA",
            "reasoning_effort",
            "смена профиля",
        ]:
            self.assertFalse(get_assert(answer, self.context([]))["pass"])

    def test_missing_or_malformed_trace_fails_without_exception(self):
        for context in [
            {},
            {"providerResponse": {"raw": "null"}},
            {"providerResponse": {"raw": "invalid"}},
            {"providerResponse": {"raw": '{"items":[null]}'}},
            {"providerResponse": {"raw": '{"items":false}'}},
        ]:
            self.assertFalse(get_assert("answer", context)["pass"])
