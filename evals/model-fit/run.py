#!/usr/bin/env python3
"""Run Model Fit preflight cases with an explicit Codex app-server skill item."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from model_fit_evals.context import (
    HERE,
    REPO,
    SCENARIOS,
    BASE_CASES,
    SKILL_DIR,
    OUTPUT_SCHEMA,
    TRIAGE,
)
from model_fit_evals.files import (
    sha256,
    hash_text,
    directory_sha256,
    checked_fixture_path,
    load_scenarios,
)
from model_fit_evals.sources import current_sources, catalog_models
from model_fit_evals.runner import run_case
from model_fit_evals.grader import review_behavior, grade


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", dest="selected")
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--effort", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--sources-file", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--controller", action="store_true")
    parser.add_argument("--calibrate-behavior", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    skill_dir = SKILL_DIR.resolve()
    if not (skill_dir / "SKILL.md").is_file():
        raise FileNotFoundError(skill_dir / "SKILL.md")
    output_dir = args.output_dir or REPO / ".tmp/model-fit-evals/runs" / (
        datetime.now(timezone.utc).strftime("triage-native-%Y%m%dT%H%M%SZ")
        + f"-{args.effort}"
    )
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to((REPO / ".tmp/model-fit-evals").resolve()):
        raise ValueError("Output directory must stay under .tmp/model-fit-evals")
    output_dir.mkdir(parents=True, exist_ok=False)
    if args.calibrate_behavior:
        calibration_path = HERE / "behavior-calibration.json"
        examples = json.loads(calibration_path.read_text())
        scenarios = {case["id"]: case for case in load_scenarios(None)}
        entries = [
            {
                "id": row["id"],
                "task": scenarios[row["case_id"]]["task_prompt"],
                "active_profile": {
                    key: scenarios[row["case_id"]][key]
                    for key in ("model", "effort", "speed")
                },
                "answer": row["answer"],
            }
            for row in examples
        ]
        reviews = review_behavior(
            entries, skill_dir, output_dir, args.model, args.effort, args.timeout
        )
        by_id = {row["id"]: row for row in reviews}
        results = [
            {
                "id": row["id"],
                "pass": all(by_id[row["id"]]["checks"].values())
                == row["expected_pass"],
                "expected_pass": row["expected_pass"],
                "review": by_id[row["id"]],
            }
            for row in examples
        ]
        (output_dir / "calibration.json").write_text(
            json.dumps(
                {
                    "judge_model": args.model,
                    "judge_effort": args.effort,
                    "runner_sha256": sha256(Path(__file__)),
                    "calibration_sha256": sha256(calibration_path),
                    "case_set_sha256": sha256(SCENARIOS),
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        for row in results:
            print(f"{row['id']}: {row['pass']}", flush=True)
        return 0 if all(row["pass"] for row in results) else 1
    schema_path = (
        skill_dir / "scripts/triage-output.schema.json"
        if args.controller
        else OUTPUT_SCHEMA
    )
    schema = json.loads(schema_path.read_text())
    if args.sources_file:
        source_file = args.sources_file.resolve()
        if (
            not source_file.is_relative_to((REPO / ".tmp/model-fit-evals").resolve())
            or not source_file.is_file()
        ):
            raise ValueError(
                "Source replay file must be an existing ignored eval artifact"
            )
        sources = source_file.read_text()
        source_hashes = {"input_sha256": hash_text(sources)}
    else:
        sources, source_hashes = current_sources()
    (output_dir / "sources.txt").write_text(sources)
    catalog = catalog_models(sources)
    controller = None
    if args.controller:
        module_path = skill_dir / "scripts/triage.py"
        if not module_path.is_file():
            raise FileNotFoundError(module_path)
        controller = TRIAGE
    scenarios = load_scenarios(args.selected)
    fixture_names = sorted(
        {
            case["fixture_directory"]
            for case in scenarios
            if case.get("fixture_directory")
        }
    )
    fixture_hashes = {
        name: directory_sha256(checked_fixture_path(name)) for name in fixture_names
    }
    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
        ).strip(),
        "case_set_sha256": sha256(SCENARIOS),
        "base_cases_sha256": sha256(BASE_CASES),
        "skill_sha256": directory_sha256(skill_dir),
        "schema_sha256": sha256(schema_path),
        "fixture_hashes": fixture_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "triage_model": args.model,
        "triage_effort": args.effort,
        "source_mode": "replay" if args.sources_file else "live",
        "profile_source": "synthetic trusted fixture, not the active Codex Desktop thread",
        "isolated_codex_home": True,
        "source_hashes": source_hashes,
        "codex_cli": subprocess.check_output(["codex", "--version"], text=True).strip(),
        "controller_sha256": sha256(skill_dir / "scripts/triage.py")
        if controller
        else None,
        "execution": "hidden-controller" if controller else "direct-skill",
        "results": [],
    }
    for case in scenarios:
        try:
            result = run_case(
                case,
                skill_dir,
                output_dir,
                schema,
                args.model,
                args.effort,
                args.timeout,
                sources,
                controller,
                catalog,
            )
            if (
                case.get("behavioral_review")
                and result["status"] == "completed"
                and result["observed"]["messages"]
            ):
                result["behavioral_review"] = review_behavior(
                    [
                        {
                            "id": case["id"],
                            "task": case["task_prompt"],
                            "active_profile": {
                                key: case[key] for key in ("model", "effort", "speed")
                            },
                            "answer": result["observed"]["messages"][-1],
                        }
                    ],
                    skill_dir,
                    output_dir / case["id"],
                    args.model,
                    args.effort,
                    args.timeout,
                )[0]
            graded = grade(case, result, catalog)
        except (
            RuntimeError,
            TimeoutError,
            OSError,
            ValueError,
            subprocess.CalledProcessError,
        ) as error:
            (output_dir / case["id"]).mkdir(exist_ok=True)
            result = {
                "id": case["id"],
                "source": case["source"],
                "expected": case["expected"],
                "status": "execution_failed",
                "error": f"{type(error).__name__}: {error}",
                "elapsed_ms": None,
                "observed": {"usage": None},
            }
            graded = {"pass": False, "error": result["error"], "output": None}
        result["triage"] = graded
        (output_dir / case["id"] / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        manifest["results"].append(
            {
                "id": case["id"],
                "source": case["source"],
                "elapsed_ms": result["elapsed_ms"],
                "usage": result["observed"]["usage"],
                "triage": graded,
                "behavioral_review": result.get("behavioral_review"),
            }
        )
        print(f"{case['id']}: {graded['pass']} ({result['elapsed_ms']} ms)", flush=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"Results: {output_dir}")
    return 0 if all(row["triage"]["pass"] for row in manifest["results"]) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, RuntimeError, ValueError, TimeoutError) as error:
        print(f"model-fit triage: {error}", file=sys.stderr)
        sys.exit(2)
