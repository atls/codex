from pathlib import Path
from types import TracebackType
from typing import Protocol, Self

from model_fit.native_input.types.json import JsonValue


class AssessmentRuntime(Protocol):
    skill_file: Path
    events: list[dict[str, JsonValue]]

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def call(
        self, method: str, params: dict[str, JsonValue], timeout: float
    ) -> dict[str, JsonValue]: ...

    def wait_turn(self, thread_id: str, turn_id: str, timeout: int) -> str: ...


class AssessmentRuntimeFactory(Protocol):
    def __call__(
        self, directory: Path, *, codex_path: str, skill_dir: Path | None = None
    ) -> AssessmentRuntime: ...
