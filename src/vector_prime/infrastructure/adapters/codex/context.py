from collections.abc import Callable

from vector_prime.application.assessment.types.request import ProfileAssessmentInput
from vector_prime.application.assessment.exceptions.context_unavailable import (
    ContextUnavailable,
)
from vector_prime.infrastructure.adapters.codex.history import unavailable_session_input
from vector_prime.infrastructure.adapters.codex.identity import executor_thread_id
from vector_prime.infrastructure.adapters.codex.transport.exceptions.rpc import (
    AppServerRPCError,
)
from vector_prime.application.submission.decoding import checked_object


def assessment_context(
    source: object, *, reader: Callable[[object], ProfileAssessmentInput]
) -> ProfileAssessmentInput:
    try:
        return reader(source)
    except AppServerRPCError as error:
        thread_id = executor_thread_id(checked_object(source))
        reason = unavailable_session_input(error, thread_id)
        if reason is None:
            raise
        raise ContextUnavailable(reason) from error
