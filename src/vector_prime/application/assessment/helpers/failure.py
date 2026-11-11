from subprocess import SubprocessError


def evaluator_failure_name(error: Exception) -> str | None:
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
        return type(error).__name__
    return None
