from typing import Any


def validated_active_profile(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("Preflight input is not an object")
    active = request.get("active_profile")
    if not isinstance(active, dict) or not all(
        field in active for field in ("model", "effort", "speed")
    ):
        raise ValueError("Active profile fields are incomplete")
    if not isinstance(active["model"], str) or not isinstance(active["effort"], str):
        raise ValueError("Active model and effort must come from session state")
    if active["speed"] is not None and not isinstance(active["speed"], str):
        raise ValueError("Active speed must be a string or null")
    return {field: active[field] for field in ("model", "effort", "speed")}
