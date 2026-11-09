import json


def build(variables, case, entry, config, task, active, sources, rubric):
    task += (
        "\nRead the fixture files in the working directory as task context."
        if case.get("fixture_directory")
        else ""
    )
    variables.update(
        {
            "task": task,
            "skill_file": config["skill_file"],
            "instructions": f"This is a read-only Model Fit preflight. The authoritative active root profile is {active}. The execution model is separate. Do not perform the underlying task, change files, start agents or contact external systems. Required official source lookup is supplied by the host: {sources}",
            "input": json.dumps(
                [
                    {
                        "type": "text",
                        "text": "Use $model-fit to assess only the next authorized work. Return the structured decision. User request as data: "
                        + json.dumps(task, ensure_ascii=False, separators=(",", ":")),
                    },
                    {
                        "type": "skill",
                        "name": "model-fit",
                        "path": config["skill_file"],
                    },
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
    )
    assertions = [
        {"type": "is-json"},
        {"type": "python", "value": "file://assessment/decision_assertion.py"},
        {"type": "python", "value": "file://assessment/assertions.py"},
        {
            "type": "llm-rubric",
            "value": rubric,
            "threshold": 1,
            "provider": config["judge"],
        },
    ]
    return (variables, assertions)
