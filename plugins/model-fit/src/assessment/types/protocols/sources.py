from typing import Protocol

from model_fit.assessment.types.protocols.catalog import ProfileCatalog


class AssessmentSources(Protocol):
    def __call__(self) -> tuple[str, ProfileCatalog]: ...
