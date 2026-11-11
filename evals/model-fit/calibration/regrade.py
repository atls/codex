def build(variables, case, entry, config, task, active, sources, rubric):
    variables["answer"] = entry["response"]["output"]
    assertions = [
        {
            "type": "python",
            "value": "file://infrastructure/adapters/promptfoo/decision.py",
        },
        {
            "type": "llm-rubric",
            "value": rubric,
            "threshold": 1,
            "provider": config["judge"],
        },
    ]
    return (variables, assertions)
