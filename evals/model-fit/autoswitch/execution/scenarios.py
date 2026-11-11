import json
from pathlib import Path
from typing import TypedDict

SUITE = Path(__file__).resolve().parents[2]


class ExecutionCase(TypedDict):
    id: str
    task: str
    expected_outputs: list[dict[str, object]]
    rubric: str | None


def execution_cases() -> list[ExecutionCase]:
    records = json.loads((SUITE / "fixtures/execution-cases.json").read_text())
    cases: list[ExecutionCase] = []
    for record in records:
        task = record["prompt"]
        if source := record.get("source_file"):
            task += "\n\n" + (SUITE / source).read_text()
        cases.append(
            {
                "id": record["id"],
                "task": task,
                "expected_outputs": record.get(
                    "expected_outputs",
                    [record["expected"]] if record.get("expected") else [],
                ),
                "rubric": record.get("rubric"),
            }
        )
    return cases
