"""CLI for one isolated Model Fit profile assessment."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from model_fit.assessment import assess
from model_fit.application.assessment.failures.source_unavailable import (
    SourceUnavailable,
)
from model_fit.application.assessment.validation import (
    empty_decision,
    validated_request,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        "--evaluator-model",
        default="gpt-6.1-sol",
        help="Model used by the evaluator; active profile belongs in the JSON input",
    )
    parser.add_argument(
        "--effort",
        "--evaluator-effort",
        default="low",
        help="Evaluator reasoning effort",
    )
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin)
        _, active, _, _ = validated_request(request)
    except (ValueError, TypeError) as error:
        print(f"model-fit triage input error: {type(error).__name__}", file=sys.stderr)
        return 2
    try:
        result = assess(request, args.model, args.effort, args.timeout)
    except SourceUnavailable as error:
        print(f"model-fit triage error: {type(error).__name__}", file=sys.stderr)
        result = empty_decision(
            active, "unknown", "Недоступен обязательный источник оценки"
        )
    except (
        OSError,
        ValueError,
        RuntimeError,
        TimeoutError,
        subprocess.SubprocessError,
        KeyError,
    ) as error:
        print(f"model-fit triage error: {type(error).__name__}", file=sys.stderr)
        result = empty_decision(
            active, "unknown", "Триаж не вернул проверенное решение"
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["decision"] != "unknown" else 1


if __name__ == "__main__":
    sys.exit(main())
