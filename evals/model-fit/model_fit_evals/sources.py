"""Read current official sources and validate catalog targets."""

from __future__ import annotations
import json
from typing import Any
from model_fit_evals.context import TRIAGE
from model_fit_evals.files import hash_text
from model_fit.preflight import official_source, supported


def current_sources() -> tuple[str, dict[str, str]]:
    sources, _ = TRIAGE.sources()
    return sources, {"input_sha256": hash_text(sources)}


def valid_official_source(value: Any) -> bool:
    return official_source(value)


def catalog_models(sources: str) -> dict[str, dict[str, Any]]:
    opening, closing = "<codex_catalog>", "</codex_catalog>"
    if sources.count(opening) != 1 or sources.count(closing) != 1:
        raise ValueError("Expected one Codex catalog in the eval sources")
    projection = json.loads(sources.split(opening, 1)[1].split(closing, 1)[0])
    if not isinstance(projection, dict):
        raise ValueError("Codex catalog projection is not an object")
    entries = projection.get("models")
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict) for entry in entries
    ):
        raise ValueError("Codex catalog models are unavailable")
    models = {entry.get("slug"): entry for entry in entries}
    if None in models or len(models) != len(entries):
        raise ValueError("Codex catalog contains missing or duplicate model slugs")
    return models


def catalog_supports_target(
    case: dict[str, Any], output: dict[str, Any], catalog: dict[str, dict[str, Any]]
) -> bool:
    model = output.get("recommended_model") or case["model"]
    effort = output.get("recommended_effort") or case["effort"]
    speed = output.get("recommended_speed") or case["speed"]
    return supported({"model": model, "effort": effort, "speed": speed}, catalog)
