from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AllowedTool:
    updated_input: dict[str, Any] | None = None


@dataclass(frozen=True)
class DeniedTool:
    reason: str


ToolAdmission = AllowedTool | DeniedTool
