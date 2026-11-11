import hashlib
import json
from pathlib import Path

SUITE = Path(__file__).resolve().parents[2]
from calibration import generate as calibration
from calibration import regrade

from . import native, ordinary, selection
from .catalog import catalog_models
from .controls import calibration_controls
from .fixtures import fixture_context, prepare_workspace
from .loading import load_scenarios

BUILDERS = {
    "native": native.build,
    "assessment": selection.build,
    "ordinary": ordinary.build,
    "calibration": calibration.build,
    "regrade": regrade.build,
}


def generate_tests(config=None):
    config = config or {}
    surface = config.get("surface", "native")
    if surface not in {"native", "assessment", "ordinary", "calibration", "regrade"}:
        raise ValueError("Unknown Model Fit eval surface")
    root = config.get("workspace_root")
    if not root:
        raise ValueError("Configured disposable workspace root is required")
    sources = (SUITE / "fixtures/preflight-sources-2026-10-16.txt").read_text()
    catalog = list(catalog_models(sources).values())
    rubric = (SUITE / "assessment/rubric.txt").read_text()
    cases = load_scenarios(config.get("case_ids"))
    for case in cases:
        case["task_context"] = fixture_context(case) or ""
    by_id = {case["id"]: case for case in cases}
    if surface == "calibration":
        entries = calibration_controls(by_id)
    elif surface == "regrade":
        saved = json.loads(
            Path(
                config.get("saved_result", SUITE / "results/assessment-full.json")
            ).read_text()
        )
        rows = (
            saved["results"]
            if isinstance(saved["results"], list)
            else saved["results"]["results"]
        )
        if any((row["testCase"]["description"] not in by_id for row in rows)):
            raise ValueError("Unknown retained scenario")
        entries = [
            row
            for row in rows
            if not by_id[row["testCase"]["description"]].get("source_failure")
            and (not by_id[row["testCase"]["description"]].get("prior_choice"))
        ]
    else:
        entries = [
            case
            for case in cases
            if (
                bool(case.get("implicit_selection_control"))
                if surface == "ordinary"
                else not case.get("implicit_selection_control")
            )
            and (
                surface != "native"
                or (not case.get("source_failure") and (not case.get("prior_choice")))
            )
        ]
    tests = []
    ids = set()
    for entry in entries:
        case = (
            by_id[entry["case_id"]]
            if surface == "calibration"
            else by_id[entry["testCase"]["description"]]
            if surface == "regrade"
            else entry
        )
        identifier = entry["id"] if surface == "calibration" else case["id"]
        if identifier in ids:
            raise ValueError("Generated test IDs must be unique")
        ids.add(identifier)
        workspace = prepare_workspace(
            root,
            identifier,
            case if surface in {"native", "assessment", "ordinary"} else None,
        )
        active = json.dumps(
            {key: case[key] for key in ("model", "effort", "speed")},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        task = case["prompt"]
        variables = {
            "scenario": case,
            "catalog": catalog,
            "workspace": workspace,
            "task": task,
            "task_context": case["task_context"],
            "active_profile": active,
            "sources": sources,
        }
        assertions = []
        variables, assertions = BUILDERS[surface](
            variables,
            case,
            entry,
            config,
            task,
            active,
            sources,
            rubric
            + (
                "\nScenario-specific quality requirements: "
                + case["quality_requirements"]
                if case.get("quality_requirements")
                else ""
            ),
        )
        tests.append(
            {
                "description": identifier,
                "vars": variables,
                "assert": assertions,
                "metadata": {
                    "sourcesSha256": hashlib.sha256(sources.encode()).hexdigest()
                },
            }
        )
    if not tests:
        raise ValueError("No scenarios match the selected surface")
    return tests
