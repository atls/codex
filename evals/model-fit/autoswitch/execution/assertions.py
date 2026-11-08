"""Check fixed task output with JSON boolean and number distinctions."""

import json
import math


def json_equal(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if type(left) in (int, float) and type(right) in (int, float):
        a, b = float(left), float(right)
        return a == b and (a != 0 or math.copysign(1, a) == math.copysign(1, b))
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            json_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def invalid_constant(value):
    raise ValueError("Invalid JSON constant")


def get_assert(output, context):
    try:
        answer = json.loads(output, parse_int=float, parse_constant=invalid_constant)
        expected = context["vars"]["expected_outputs"]
        if not isinstance(expected, list):
            raise ValueError("Expected outputs must be an array")
        passed = (
            any(json_equal(answer, candidate) for candidate in expected)
            if expected
            else isinstance(answer, dict)
            and isinstance(answer.get("title"), str)
            and isinstance(answer.get("context"), str)
            and isinstance(answer.get("acceptance"), list)
            and bool(answer["acceptance"])
            and all(isinstance(entry, str) for entry in answer["acceptance"])
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        return {
            "pass": False,
            "score": 0,
            "reason": "Task result is not valid JSON or lacks fixed criteria",
        }
    return {
        "pass": passed,
        "score": 1 if passed else 0,
        "reason": "Task result contract passed"
        if passed
        else "Task result differs from its fixed criteria",
    }
