from collections.abc import Callable

from vector_prime.application.assessment.types.request import ProfileAssessmentInput
from vector_prime.application.assessment.exceptions.context_unavailable import (
    ContextUnavailable,
)
from vector_prime.infrastructure.adapters.codex.history import unavailable_session_input
from vector_prime.application.assessment.types.context import ContextSource
from vector_prime.infrastructure.adapters.codex.transport.exceptions.rpc import (
    AppServerRPCError,
)


def assessment_context(
    source: ContextSource, *, reader: Callable[[ContextSource], ProfileAssessmentInput]
) -> ProfileAssessmentInput:
    try:
        return reader(source)
    except AppServerRPCError as error:
        reason = unavailable_session_input(error, source.thread_id)
        if reason is None:
            raise
        raise ContextUnavailable(reason) from error
