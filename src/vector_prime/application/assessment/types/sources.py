from typing import Protocol

from vector_prime.application.assessment.types.catalog import ProfileCatalog


class AssessmentSources(Protocol):
    def __call__(self) -> tuple[str, ProfileCatalog]: ...
