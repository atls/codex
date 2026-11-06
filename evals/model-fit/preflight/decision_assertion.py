"""Promptfoo assertion against the production Model Fit decision validator."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCRIPTS = Path(__file__).resolve().parents[3] / "plugins/model-fit/scripts"
sys.path.insert(0, str(SCRIPTS.parent / "src"))
from model_fit.application.assessment import validation as DECISIONS
from model_fit.infrastructure.assessment.sources.catalog import NativeCatalog
from preflight.scenarios.expectations import assert_expected_decision


def get_assert(output, context):
    variables = context["vars"]
    case = variables["scenario"]
    try:
        answer = json.loads(output)
        active = {key: case[key] for key in ("model", "effort", "speed")}
        models = NativeCatalog.from_projection({"models": variables["catalog"]})
        decision = DECISIONS.validate(answer, active, models)
        assert_expected_decision(decision, active, case)
    except (ValueError, TypeError, KeyError) as error:
        return {"pass": False, "score": 0, "reason": str(error)}
    return {
        "pass": True,
        "score": 1,
        "reason": "Production decision contract passed; semantic rubric is separate",
    }
