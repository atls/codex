from typing import Protocol

from model_fit.application.assessment.ports.catalog import Catalog


class Sources(Protocol):
    def __call__(self) -> tuple[str, Catalog]: ...
