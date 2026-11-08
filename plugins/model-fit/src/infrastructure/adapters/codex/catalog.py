from typing import Any


class NativeCatalog:
    def __init__(self, models: dict[str, dict[str, Any]]):
        self.entries = models

    @classmethod
    def from_projection(cls, projection: dict[str, Any]):
        entries = projection.get("models")
        if not isinstance(entries, list) or not entries:
            raise ValueError("Codex model catalog is empty")
        try:
            return cls(cls.index_entries(entries))
        except ValueError as error:
            raise ValueError(
                "Codex model catalog contains invalid or duplicate entries"
            ) from error

    @staticmethod
    def index_entries(entries):
        if not isinstance(entries, list) or any(
            (not isinstance(row, dict) for row in entries)
        ):
            raise ValueError("Codex catalog models are unavailable")
        models = {row.get("slug"): row for row in entries}
        if None in models or len(models) != len(entries):
            raise ValueError("Codex catalog contains missing or duplicate model slugs")
        return models

    def supported(self, profile: dict[str, Any]) -> bool:
        entry = self.entries.get(profile["model"])
        if not entry or entry.get("visibility") != "list":
            return False
        levels = entry.get("supported_reasoning_levels") or []
        efforts = {
            level.get("effort") if isinstance(level, dict) else level
            for level in levels
        }
        if profile["effort"] not in efforts:
            return False
        speed = profile["speed"]
        return speed in (None, "standard") or speed in (
            entry.get("additional_speed_tiers") or []
        )
