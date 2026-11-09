from typing import Protocol

from model_fit.assessment.interfaces.catalog import ProfileCatalog


class AssessmentSources(Protocol):
    def __call__(self) -> tuple[str, ProfileCatalog]: ...
