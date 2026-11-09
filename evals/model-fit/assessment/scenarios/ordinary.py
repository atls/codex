def build(variables, case, entry, config, task, active, sources, rubric):
    assertions = [
        {"type": "python", "value": "file://assessment/ordinary/assertions.py"},
        {
            "type": "llm-rubric",
            "threshold": 1,
            "value": "Explain git status --short: it is the compact status of changed/untracked files. Answer the question without profile-selection advice, invoking a skill or tools.",
            "provider": config["judge"],
        },
    ]
    return (variables, assertions)
