import json


def build(variables, case, entry, config, task, active, sources, rubric):
    variables["input"] = json.dumps({"case_id": case["id"]}, separators=(",", ":"))
    assertions = [
        {"type": "is-json"},
        {"type": "python", "value": "file://preflight/decision_assertion.py"},
        {"type": "python", "value": "file://controller/assertions.py"},
    ]
    if not case.get("source_failure") and not case.get("prior_choice"):
        assertions.append(
            {
                "type": "llm-rubric",
                "value": rubric,
                "threshold": 1,
                "provider": config["judge"],
            }
        )
    return variables, assertions
