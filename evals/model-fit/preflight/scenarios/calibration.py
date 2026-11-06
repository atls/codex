import json


def build(variables, case, entry, config, task, active, sources, rubric):
    variables["answer"] = json.dumps(
        entry["answer"], ensure_ascii=False, separators=(",", ":")
    )
    assertions = [
        {
            "type": "llm-rubric" if entry["expected_pass"] else "not-llm-rubric",
            "value": rubric,
            "threshold": 1,
            "provider": config["judge"],
        }
    ]
    return variables, assertions
