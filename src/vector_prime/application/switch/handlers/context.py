from vector_prime.application.assessment.helpers.context import restore_context
from vector_prime.application.assessment.types.context import (
    ContextAugmentation,
    NativeProfileObservation,
    PriorClarification,
    UnfinishedRequest,
)
from vector_prime.application.assessment.types.request import ProfileAssessmentInput
from vector_prime.application.switch.types.reconciliation import ReconciledSubmission
from vector_prime.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from vector_prime.application.handoff.guards.continuation import reuses_original_input
from vector_prime.application.submission.types.input import SubmissionInput
from vector_prime.application.submission.helpers import content as codec


def restore_work_context(
    event: SubmissionInput,
    request: ProfileAssessmentInput,
    reconciled: ReconciledSubmission,
    *,
    conversation: NativeConversationFactory,
) -> ProfileAssessmentInput:
    choice: NativeProfileObservation | PriorClarification | None = None
    context_turn = reconciled.profile_context_turn_id
    context_state = reconciled.profile_context_state
    if context_turn is not None and context_state is not None:
        if context_state.get("native_profile") is not None:
            choice = NativeProfileObservation(
                context_state["native_profile"], context_turn == event.turn_id
            )
        else:
            with conversation(event.working_directory) as app:
                choice = PriorClarification(
                    codec.input_text(
                        app.source_input(
                            event.thread_id, context_turn, include_steering=True
                        )
                    )
                )
    unfinished = None
    pending = reconciled.pending_transfer
    if pending is not None:
        content = None
        if "input" in request:
            with conversation(event.working_directory) as app:
                content = app.handoff_input(event.thread_id, pending.source())
        unfinished = UnfinishedRequest(
            pending.prompt, content, reuses_original_input(event.turn_id, pending)
        )
    return restore_context(request, ContextAugmentation(choice, unfinished))
