from model_fit.application.switch import lifecycle as switch_lifecycle
from collections.abc import Callable
from model_fit.application.switch.admission.types.input import ToolAdmissionInput
from model_fit.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.application.assessment.types.cache import (
    ResultCache,
)
from model_fit.application.assessment.lifecycle import load_blocking_recommendation
from model_fit.application.switch.types.state import ProcessSnapshot
from model_fit.application.switch.types.storage import TransferStateStore
from model_fit.application.switch.types.audit import AuditWriter
from model_fit.application.assessment import lifecycle as assessment_lifecycle
from model_fit.application.assessment.types.state import PendingAssessmentRecord
from model_fit.application.assessment.types.result import UnknownAssessment
from model_fit.application.submission.types.input import SubmissionInput


def recover_unsubmitted_successor(
    event: ToolAdmissionInput,
    state: ProcessSnapshot,
    *,
    conversation: NativeConversationFactory,
    working_directory: Callable[[], str],
    store: TransferStateStore,
    recommendations: ResultCache,
    audit: AuditWriter,
) -> bool:
    turn_id = event.turn_id
    if not isinstance(turn_id, str):
        return False
    pending = state["pending_assessment"]
    if pending is None:
        return False
    try:
        with conversation(working_directory()) as app:
            successor = app.unsubmitted_successor(
                event.thread_id, pending["turn_id"], turn_id
            )
        if successor is True:
            with store.transaction(
                event.thread_id,
                nonblocking=True,
                operation="pre_tool_use",
                turn_id=event.turn_id,
            ) as slot:
                if (
                    slot.load() == state
                    and load_blocking_recommendation(
                        event.thread_id,
                        recommendations=recommendations,
                    )
                    is None
                ):
                    switch_lifecycle.admit(
                        slot,
                        turn_id,
                        "unknown",
                        state.get("profile_context_turn_id"),
                        supersede_assessment=True,
                    )
                    audit(
                        event.thread_id,
                        event.turn_id,
                        "auto_unknown",
                        {
                            "hook_event": "PreToolUse",
                            "reason_code": "native_turn_without_submission",
                            "state_phase": state["phase"],
                        },
                    )
                    return True
    except (OSError, ValueError, RuntimeError):
        pass
    return False


def admit_assessment_recovery(
    event: SubmissionInput,
    pending: PendingAssessmentRecord,
    error: Exception,
    *,
    store: TransferStateStore,
    audit: AuditWriter,
) -> UnknownAssessment | None:
    thread_id = event.thread_id
    recovery = assessment_lifecycle.recover(error)
    if recovery is not None:
        try:
            with store.transaction(
                thread_id,
                nonblocking=True,
                operation="assessment",
                turn_id=event.turn_id,
            ) as slot:
                continued = switch_lifecycle.abstain_assessment(slot, pending)
        except BlockingIOError:
            continued = False
        if continued:
            audit(
                thread_id,
                event.turn_id,
                "auto_assessment_error:" + type(error).__name__,
                {
                    "hook_event": "assessment",
                    "reason_code": "assessment_failed_continue",
                    "assessment_generation": pending["generation"],
                },
                error=error,
            )
            audit(
                thread_id,
                event.turn_id,
                "auto_unknown",
                {
                    "hook_event": "assessment",
                    "reason_code": "assessment_failed_continue",
                },
            )
            return recovery
    return None
