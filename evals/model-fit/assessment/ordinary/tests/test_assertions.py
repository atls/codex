import json
import unittest

from assessment.ordinary.assertions import get_assert


class OrdinaryDialogueTests(unittest.TestCase):
    def context(self, items):
        return {"providerResponse": {"raw": json.dumps({"items": items})}}

    def test_valid_trace_accepts_names_without_lexical_filtering(self):
        for answer in (
            "git status --short shows changed files",
            "Luna is the name of the cat.",
            "Astra is a flower name.",
        ):
            with self.subTest(answer=answer):
                self.assertTrue(
                    get_assert(
                        answer,
                        self.context(
                            [{"type": "agent_message"}, {"type": "reasoning"}]
                        ),
                    )["pass"]
                )

    def test_native_tool_activity_fails_the_trace_gate(self):
        self.assertFalse(
            get_assert("A plain answer", self.context([{"type": "command_execution"}]))[
                "pass"
            ]
        )
        self.assertTrue(get_assert("Use a stronger model", self.context([]))["pass"])

    def test_missing_or_malformed_trace_fails_without_exception(self):
        for context in [
            {},
            {"providerResponse": {"raw": "{}"}},
            {"providerResponse": {"raw": '{"items":null}'}},
            {"providerResponse": {"raw": "null"}},
            {"providerResponse": {"raw": "invalid"}},
            {"providerResponse": {"raw": '{"items":[null]}'}},
            {"providerResponse": {"raw": '{"items":false}'}},
        ]:
            self.assertFalse(get_assert("answer", context)["pass"])
