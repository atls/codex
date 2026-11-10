from model_fit.application.assessment.types.profile import ActiveProfile
from typing import Self
from model_fit.application.submission.types.json import JsonValue
from model_fit.application.submission.constraints.content import (
    checked_content,
    checked_object,
    native_text,
)


class NativeCatalog:
    def __init__(self, models: dict[str, dict[str, JsonValue]]):
        self.entries = models

    @classmethod
    def from_projection(cls, projection: object) -> Self:
        entries = checked_object(projection).get("models")
        if not isinstance(entries, list) or not entries:
            raise ValueError("Codex model catalog is empty")
        try:
            return cls(cls.index_entries(entries))
        except ValueError as error:
            raise ValueError(
                "Codex model catalog contains invalid or duplicate entries"
            ) from error

    @staticmethod
    def index_entries(entries: object) -> dict[str, dict[str, JsonValue]]:
        if not isinstance(entries, list) or any(
            (not isinstance(row, dict) for row in entries)
        ):
            raise ValueError("Codex catalog models are unavailable")
        models = {native_text(row.get("slug")): row for row in checked_content(entries)}
        if None in models or len(models) != len(entries):
            raise ValueError("Codex catalog contains missing or duplicate model slugs")
        return models

    def supported(self, profile: ActiveProfile) -> bool:
        entry = self.entries.get(profile["model"])
        if not entry or entry.get("visibility") != "list":
            return False
        levels = entry.get("supported_reasoning_levels") or []
        if not isinstance(levels, list):
            return False
        efforts = [
            level.get("effort") if isinstance(level, dict) else level
            for level in levels
        ]
        if profile["effort"] not in efforts:
            return False
        speed = profile["speed"]
        tiers = entry.get("additional_speed_tiers") or []
        return speed in (None, "standard") or (
            isinstance(tiers, list) and speed in tiers
        )
