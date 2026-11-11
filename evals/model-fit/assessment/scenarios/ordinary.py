def build(variables, case, entry, config, task, active, sources, rubric):
    assertions = [
        {"type": "python", "value": "file://assessment/ordinary/assertions.py"},
        {
            "type": "llm-rubric",
            "threshold": 1,
            "value": "Answer the supplied ordinary question correctly, without unsolicited model/profile-selection advice, invoking a skill or tools. Proper names and quoted model names alone are not profile-selection advice. Task: {{task}}",
            "provider": config["judge"],
        },
    ]
    return (variables, assertions)
