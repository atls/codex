from vector_prime.application.assessment.types.catalog import ProfileCatalog
from vector_prime.application.assessment.types.profile import ActiveProfile


def require_profiles(
    active: ActiveProfile, evaluator: ActiveProfile, catalog: ProfileCatalog
) -> None:
    if not catalog.supported(active):
        raise ValueError("Active profile is absent from the local catalog")
    if not catalog.supported(evaluator):
        raise ValueError("Evaluator profile is absent from the local catalog")
