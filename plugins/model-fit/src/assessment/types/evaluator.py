from model_fit.native_input.types.json import JsonValue
from typing import Protocol


class AssessmentEvaluator(Protocol):
    def __call__(
        self,
        instructions: str,
        prompt: str,
        model: str,
        effort: str,
        timeout: int,
        diagnostics: dict[str, JsonValue] | None,
        *,
        native_input: list[dict[str, JsonValue]] | None = None,
    ) -> object: ...
