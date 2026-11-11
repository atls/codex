"""Promptfoo assertion against the production Model Fit decision validator."""

import json
from vector_prime.application.assessment.decision import validate
from vector_prime.infrastructure.adapters.codex.catalog import NativeCatalog

from assessment.scenarios.expectations import assert_expected_decision


def get_assert(output, context):
    variables = context["vars"]
    case = variables["scenario"]
    try:
        answer = json.loads(output)
        active = {key: case[key] for key in ("model", "effort", "speed")}
        models = NativeCatalog.from_projection({"models": variables["catalog"]})
        decision = validate(answer, active, models)
        assert_expected_decision(decision, active, case)
    except (ValueError, TypeError, KeyError) as error:
        return {"pass": False, "score": 0, "reason": str(error)}
    return {
        "pass": True,
        "score": 1,
        "reason": "Production decision contract passed; semantic rubric is separate",
    }
