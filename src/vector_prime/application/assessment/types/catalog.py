from vector_prime.application.assessment.types.profile import ActiveProfile
from typing import Protocol


class ProfileCatalog(Protocol):
    def supported(self, profile: ActiveProfile) -> bool: ...
