"""Run the live relevance classifier on sanitized Model Fit replay cases."""

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
from vector_prime.application.answer.relevance import classify_answer
from vector_prime.infrastructure.adapters.codex.answer import evaluate_relevance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", dest="selected")
    args = parser.parse_args()
    cases = json.loads((HERE / "fixtures/replay-answer-cases.json").read_text())
    selected = set(args.selected or [case["id"] for case in cases])
    if selected - {case["id"] for case in cases}:
        parser.error("Unknown replay-answer case")
    passed = True
    for case in cases:
        if case["id"] not in selected:
            continue
        started = time.monotonic()
        try:
            observed = classify_answer(
                case["request"],
                case["task_context"],
                case["answer"],
                evaluator=evaluate_relevance,
            )
            result = {
                "id": case["id"],
                "expected": case["expected"],
                "observed": observed,
                "pass": observed == case["expected"],
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        except (OSError, ValueError, RuntimeError, TimeoutError) as error:
            result = {
                "id": case["id"],
                "expected": case["expected"],
                "observed": None,
                "pass": False,
                "error": type(error).__name__,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        passed = passed and result["pass"]
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
