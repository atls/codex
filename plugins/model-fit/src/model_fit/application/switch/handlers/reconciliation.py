from __future__ import annotations
from model_fit.application.handoff.types.reconciliation import ReconciledHandoff

from model_fit.application.handoff import lifecycle as handoff_lifecycle
from model_fit.application.switch import lifecycle as switch_lifecycle


from model_fit.application.switch.types.audit import AuditWriter
from model_fit.application.assessment.types.execution import AssessmentContextReader
from model_fit.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.application.assessment.types.state import PendingAssessmentRecord
from model_fit.application.switch.types.disposition import (
    TurnDisposition,
)

from model_fit.application.submission.types.input import SubmissionInput
from model_fit.application.switch.types.storage import TransferStateStore

from model_fit.application.switch.types.reconciliation import ReconciledSubmission


def reconcile(
    event: SubmissionInput,
    *,
    expected_submission: PendingAssessmentRecord | None,
    audit: AuditWriter,
    conversation: NativeConversationFactory,
    read_context: AssessmentContextReader,
    store: TransferStateStore,
) -> ReconciledSubmission | TurnDisposition | None:
    thread_id = event.thread_id
    turn_id = event.turn_id
    prompt = event.text
    if not all(
        (isinstance(value, str) and value for value in (thread_id, turn_id))
    ) or not isinstance(prompt, str):
        raise ValueError("Incomplete Desktop hook input")
    pending = None
    profile_context_turn_id = None
    profile_context_state = None
    with store.transaction(
        thread_id, operation="prompt_submit", turn_id=turn_id
    ) as slot:
        prior = slot.load()
        switch_lifecycle.require_submission(slot, expected_submission)
        if prior is not None and prior["phase"] == "submitted":
            prior = None
        fresh_session = prior is None or (
            prior["phase"] == "passed" and prior.get("profile_context_turn_id") is None
        )
        if prior is not None and prior["phase"] == "passed":
            if prior["source_turn_id"] == turn_id and expected_submission is None:
                audit(thread_id, turn_id, "auto_steer")
                return None
            profile_context_turn_id = prior.get("profile_context_turn_id")
            if profile_context_turn_id is not None:
                profile_context_state = prior
            else:
                handoff_lifecycle.release(slot)
            prior = None
        if prior is not None:
            reconciled = handoff_lifecycle.reconcile(
                slot,
                event,
                prior,
                audit=audit,
                conversation=conversation,
                read_context=read_context,
            )
            if not isinstance(reconciled, ReconciledHandoff):
                return reconciled
            pending = reconciled.pending_transfer
        handoff_snapshot = slot.load()
    return ReconciledSubmission(
        pending,
        handoff_snapshot,
        profile_context_turn_id,
        profile_context_state,
        fresh_session,
    )
