from model_fit.application.assessment.types.catalog import ProfileCatalog
from model_fit.application.assessment.types.profile import ActiveProfile


def require_profiles(
    active: ActiveProfile, evaluator: ActiveProfile, catalog: ProfileCatalog
) -> None:
    if not catalog.supported(active):
        raise ValueError("Active profile is absent from the local catalog")
    if not catalog.supported(evaluator):
        raise ValueError("Evaluator profile is absent from the local catalog")
