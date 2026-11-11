from dataclasses import dataclass
from vector_prime.application.submission.types.json import JsonValue


@dataclass(frozen=True)
class AllowedTool:
    updated_input: dict[str, JsonValue] | None = None


@dataclass(frozen=True)
class DeniedTool:
    reason: str


ToolAdmission = AllowedTool | DeniedTool
