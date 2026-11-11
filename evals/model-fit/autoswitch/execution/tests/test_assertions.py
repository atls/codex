import json
import unittest

from autoswitch.execution.assertions import get_assert
from autoswitch.execution.scenarios import execution_cases


class TaskResultTests(unittest.TestCase):
    def setUp(self):
        cases = execution_cases()
        trace = next(
            (case for case in cases if case["id"] == "stale-writer-counterexample")
        )
        self.context = {"vars": {"expected_outputs": trace["expected_outputs"]}}

    def test_both_language_neutral_numeric_equality_operators_are_valid(self):
        for comparison in ["==", "==="]:
            self.assertTrue(
                get_assert(
                    json.dumps(
                        {"violation": True, "event": "e4", "comparison": comparison}
                    ),
                    self.context,
                )["pass"]
            )

    def test_stale_acceptance_wrong_event_and_wrong_operator_fail(self):
        for answer in [
            {"violation": False, "event": "e4", "comparison": "=="},
            {"violation": True, "event": "e1", "comparison": "=="},
            {"violation": True, "event": "e4", "comparison": "<="},
        ]:
            self.assertFalse(get_assert(json.dumps(answer), self.context)["pass"])

    def test_json_boolean_number_distinction_and_nested_shape_are_preserved(self):
        for answer, expected, passed in [
            ("true", 1, False),
            ("1", True, False),
            ("1.0", 1, True),
            ("9007199254740993", 9007199254740992, False),
            ("9007199254740993", 9007199254740993, True),
            ('{"a":[true]}', {"a": [1]}, False),
            ('{"b":2,"a":1}', {"a": 1, "b": 2}, True),
            ("[1,2]", [2, 1], False),
            ('{"a":1,"extra":2}', {"a": 1}, False),
            ("-0", 0, True),
        ]:
            with self.subTest(answer=answer):
                self.assertEqual(
                    get_assert(answer, {"vars": {"expected_outputs": [expected]}})[
                        "pass"
                    ],
                    passed,
                )

    def test_invalid_json_or_missing_criteria_fails_without_exception(self):
        for answer in ["not JSON", "NaN", "Infinity"]:
            self.assertFalse(get_assert(answer, self.context)["pass"])
        self.assertFalse(get_assert("{}", {})["pass"])

    def test_unfixed_issue_draft_shape_requires_nonempty_string_acceptance_array(self):
        context = {"vars": {"expected_outputs": []}}
        answer = {"title": "task", "context": "why", "acceptance": ["check"]}
        self.assertTrue(get_assert(json.dumps(answer), context)["pass"])
        for acceptance in [[], [True], "check", [""], ["   "]]:
            self.assertFalse(
                get_assert(json.dumps(answer | {"acceptance": acceptance}), context)[
                    "pass"
                ]
            )


class DraftFieldTests(unittest.TestCase):
    def test_blank_title_and_context_fail_before_semantic_grading(self):
        valid = {
            "title": "Search",
            "context": "Use local snapshots",
            "acceptance": ["Exact phrase search"],
        }
        for field in ("title", "context"):
            for blank in ("", "   "):
                with self.subTest(field=field, blank=blank):
                    self.assertFalse(
                        get_assert(
                            json.dumps(valid | {field: blank}),
                            {"vars": {"expected_outputs": []}},
                        )["pass"]
                    )
