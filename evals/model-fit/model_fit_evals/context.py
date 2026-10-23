"""Locate the candidate skill and its isolated Codex controller."""

from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
SCENARIOS = HERE / "triage-cases.json"
BASE_CASES = HERE / "cases.json"
SKILL_DIR = REPO / "plugins/model-fit/skills/model-fit"
OUTPUT_SCHEMA = SKILL_DIR / "scripts/triage-output.schema.json"


def load_triage_module(module_path: Path) -> Any:
    sys.path.insert(0, str(module_path.parent))
    spec = importlib.util.spec_from_file_location("model_fit_triage", module_path)
    if not spec or not spec.loader:
        raise RuntimeError("Cannot load Model Fit controller")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SKILL_DIR_RESOLVED = SKILL_DIR.resolve()
TRIAGE = load_triage_module(SKILL_DIR / "scripts/triage.py")
AppServer = TRIAGE.AppServer
MODEL_SELECTION_URL = "https://developers.openai.com/api/docs/guides/model-selection.md"
REASONING_URL = "https://developers.openai.com/api/docs/guides/reasoning.md"
