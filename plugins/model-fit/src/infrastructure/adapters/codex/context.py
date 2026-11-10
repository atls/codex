from collections.abc import Callable

from model_fit.assessment.types.request import ProfileAssessmentInput
from model_fit.autoswitch.exceptions.context_unavailable import ContextUnavailable
from model_fit.infrastructure.adapters.codex.history import unavailable_session_input
from model_fit.infrastructure.adapters.codex.identity import executor_thread_id
from model_fit.infrastructure.adapters.codex.transport.rpc_error import (
    AppServerRPCError,
)
from model_fit.native_input.validation import checked_object


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
