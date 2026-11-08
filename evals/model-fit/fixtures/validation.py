"""Validate public evaluation fixtures independently of package construction."""

import json
from pathlib import Path

FORBIDDEN_TEXT = ("/Users/", "codex://threads/", "-----BEGIN PRIVATE KEY-----")
FIXTURES = (
    "fixtures/cases.json",
    "fixtures/triage-cases.json",
    "fixtures/replay-answer-cases.json",
    "fixtures/behavior-calibration.json",
)


def validate_fixtures(directory: Path | None = None) -> None:
    directory = directory or Path(__file__).resolve().parents[1]
    for name in FIXTURES:
        content = (directory / name).read_text()
        json.loads(content)
        if (
            any(value in content for value in FORBIDDEN_TEXT)
            or "data:image/" in content
        ):
            raise ValueError(f"Public eval fixture contains private input: {name}")


if __name__ == "__main__":
    validate_fixtures()
