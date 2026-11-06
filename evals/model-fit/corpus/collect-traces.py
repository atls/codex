"""Project exact-turn native corpus executor traces after terminal Promptfoo CLI."""

import argparse
import importlib.util
import json
from pathlib import Path

PATH = Path(__file__).with_name("trace.py")
SPEC = importlib.util.spec_from_file_location("measured_stack_trace", PATH)
TRACE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRACE)


def collect(result, database):
    rows = (
        result["results"]
        if isinstance(result["results"], list)
        else result["results"]["results"]
    )
    projections = []
    for row in rows:
        metadata = row["response"].get("metadata", {})
        stage = metadata.get("corpusStages", {}).get("execution", {})
        response = stage.get("response") or {}
        native = response.get("metadata", {}).get("codexAppServer", {})
        profile = metadata.get("execution_profile") or {}
        if result.get("evalId") and native.get("threadId") and native.get("turnId"):
            trace = TRACE.collect(
                {
                    "database": database,
                    "evaluationId": result["evalId"],
                    "threadId": native["threadId"],
                    "turnId": native["turnId"],
                    "model": profile["model"],
                    "effort": profile["effort"],
                }
            )
        else:
            trace = {
                "status": "not-invoked"
                if stage.get("status") == "not-invoked"
                else "unknown",
                "executionModel": None,
                "spans": [],
            }
        projections.append(
            {
                "case": row["testCase"]["description"],
                "mode": metadata.get("mode"),
                "executionTrace": trace,
                "preflightTrace": {
                    "status": "unknown"
                    if metadata.get("model_fit_invoked")
                    else "not-invoked",
                    "reason": "Preflight native sampling tracing is not configured; observed launch profile is separate",
                },
            }
        )
    return projections


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    Path(args.output).write_text(
        json.dumps(
            collect(json.loads(Path(args.result).read_text()), args.database), indent=2
        )
    )
