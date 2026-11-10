from subprocess import SubprocessError

from model_fit.application.assessment.errors.evaluation import EvaluationError


def evaluation_error(error: Exception) -> EvaluationError | None:
    if isinstance(
        error,
        (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
            TimeoutError,
            SubprocessError,
        ),
    ):
        return EvaluationError(type(error).__name__)
    return None
