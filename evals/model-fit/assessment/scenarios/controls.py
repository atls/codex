import json
from pathlib import Path

SUITE = Path(__file__).resolve().parents[2]


def calibration_controls(cases):
    controls = json.loads((SUITE / "fixtures/behavior-calibration.json").read_text())
    additions = json.loads((SUITE / "calibration/controls.json").read_text())
    for entry in additions:
        if entry.pop("inherit_active_profile", False):
            case = cases[entry["case_id"]]
            entry["answer"] = {
                **{f"active_{key}": case[key] for key in ("model", "effort", "speed")},
                **entry["answer"],
            }
    controls.extend(additions)
    if len({entry["id"] for entry in controls}) != len(controls):
        raise ValueError("Calibration IDs must be unique")
    if any((entry["case_id"] not in cases for entry in controls)):
        raise ValueError("Unknown calibration scenario")
    return controls
