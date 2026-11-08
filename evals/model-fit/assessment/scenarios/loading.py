import json
from pathlib import Path

SUITE = Path(__file__).resolve().parents[2]


def load_scenarios(selected=None):
    originals = json.loads((SUITE / "fixtures/cases.json").read_text())
    base = {case["id"]: case for case in originals}
    if len(base) != len(originals):
        raise ValueError("Base scenario IDs must be unique")
    specs = json.loads((SUITE / "fixtures/triage-cases.json").read_text())
    ids = {spec["id"] for spec in specs}
    if len(ids) != len(specs):
        raise ValueError("Triage scenario IDs must be unique")
    if missing := sorted(set(selected or []) - ids):
        raise ValueError(f"Unknown scenarios: {', '.join(missing)}")
    cases = []
    for spec in specs:
        if selected and spec["id"] not in selected:
            continue
        if spec.get("base_case_id") is not None and spec["base_case_id"] not in base:
            raise ValueError("Unknown base scenario")
        case = {**base.get(spec.get("base_case_id"), {}), **spec}
        case["task_prompt"] = case["prompt"]
        case["expected_decisions"] = spec.get(
            "expected_decisions", [spec.get("expected_decision")]
        )
        case["allowed_recommendations"] = spec.get("allowed_recommendations", [])
        cases.append(case)
    return cases
