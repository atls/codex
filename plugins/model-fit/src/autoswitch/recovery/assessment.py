"""Recover technical assessment failures only through the current generation fence."""

import subprocess
from model_fit.autoswitch.lifecycle import submission as submission_lifecycle
from model_fit.autoswitch.state.types.record import PendingAssessmentRecord
from model_fit.autoswitch.state.types.storage import TransferStateStore
from model_fit.autoswitch.types.audit import AuditWriter
from model_fit.autoswitch.types.disposition import UnknownAssessment
from model_fit.submission.types.input import SubmissionInput


def recover_assessment(
    event: SubmissionInput,
    pending: PendingAssessmentRecord,
    error: Exception,
    *,
    store: TransferStateStore,
    audit: AuditWriter,
) -> UnknownAssessment | None:
    thread_id = event.thread_id
    if isinstance(
        error,
        (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
            TimeoutError,
            subprocess.SubprocessError,
        ),
    ):
        try:
            with store.transaction(
                thread_id,
                nonblocking=True,
                operation="assessment",
                turn_id=event.turn_id,
            ) as slot:
                continued = submission_lifecycle.abstain_assessment(slot, pending)
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
            return UnknownAssessment(
                "The evaluator is unavailable (" + type(error).__name__ + ")."
            )
    return None
