from typing import Protocol


class AnswerEvaluator(Protocol):
    def __call__(self, prompt: str, /) -> object: ...
