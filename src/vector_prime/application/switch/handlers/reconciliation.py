from __future__ import annotations
from vector_prime.application.handoff.helpers.instruction import transfer_instruction
from vector_prime.application.handoff.types.reconciliation import (
    ReconciliationDenied,
    TransferContinued,
)
from vector_prime.application.handoff.types.replay import ReplayBound
from vector_prime.application.switch.denial import block_prompt

from vector_prime.application.handoff import lifecycle as handoff_lifecycle
from vector_prime.application.switch import lifecycle as switch_lifecycle


from vector_prime.application.switch.types.audit import AuditWriter
from vector_prime.application.assessment.types.execution import AssessmentContextReader
from vector_prime.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from vector_prime.application.assessment.types.state import PendingAssessment
from vector_prime.application.switch.types.disposition import (
    BlockedTurn,
    ContinueWork,
    PreparedTransfer,
    TurnDisposition,
    WorkContext,
)

from vector_prime.application.submission.types.input import SubmissionInput
from vector_prime.application.switch.types.storage import TransferStateStore

from vector_prime.application.switch.types.reconciliation import ReconciledSubmission


def reconcile(
    event: SubmissionInput,
    *,
    expected_submission: PendingAssessment | None,
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
            if reconciled is None:
                return None
            if isinstance(reconciled, TransferContinued):
                return PreparedTransfer(thread_id, turn_id, transfer_instruction(prior))
            if isinstance(reconciled, ReplayBound):
                return ContinueWork(WorkContext.REPLAY)
            if isinstance(reconciled, ReconciliationDenied):
                if reconciled.reason_code is None:
                    return BlockedTurn(reconciled.reason)
                return block_prompt(
                    thread_id,
                    turn_id,
                    reconciled.reason_code,
                    reconciled.reason,
                    prior["phase"],
                    audit=audit,
                )
            pending = reconciled.pending_transfer
        handoff_snapshot = slot.load()
    return ReconciledSubmission(
        pending,
        handoff_snapshot,
        profile_context_turn_id,
        profile_context_state,
        fresh_session,
    )
