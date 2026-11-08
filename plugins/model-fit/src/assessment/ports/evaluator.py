from typing import Any, Protocol


class Evaluator(Protocol):
    def __call__(
        self,
        instructions: str,
        prompt: str,
        model: str,
        effort: str,
        timeout: int,
        diagnostics: dict[str, Any] | None,
        *,
        native_input: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...
