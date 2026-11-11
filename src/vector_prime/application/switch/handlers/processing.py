from __future__ import annotations

from vector_prime.application.assessment.exceptions.context_unavailable import (
    ContextUnavailable,
)

from vector_prime.application.switch import lifecycle as switch_lifecycle


from vector_prime.application.switch.types.reconciliation import ReconciledSubmission
from vector_prime.application.switch.handlers.reconciliation import reconcile
from vector_prime.application.switch.handlers.context import (
    restore_work_context,
)
from vector_prime.application.switch.handlers.decision import apply_decision
from vector_prime.application.assessment.types.execution import AssessmentRunner
from vector_prime.application.switch.types.audit import AuditWriter
from vector_prime.application.assessment.types.execution import AssessmentContextReader
from vector_prime.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from vector_prime.application.submission.helpers import content as codec
from vector_prime.application.assessment.types.state import PendingAssessment
from vector_prime.application.switch.types.disposition import (
    TurnDisposition,
    TurnNotice,
)
from vector_prime.application.handoff.control_message import CONTROL_PROMPTS

from vector_prime.application.submission.types.input import SubmissionInput
from vector_prime.application.assessment.types.cache import (
    ResultCache,
)
from vector_prime.application.switch.types.storage import TransferStateStore
from vector_prime.application.switch.admission.recommendation import (
    blocking_recommendation,
)
from vector_prime.application.assessment.lifecycle import load_blocking_recommendation
from vector_prime.application.handoff.types.clock import Clock


def evaluate(
    event: SubmissionInput,
    *,
    expected_submission: PendingAssessment | None = None,
    assessor: AssessmentRunner,
    audit: AuditWriter,
    recommendations: ResultCache,
    clock: Clock,
    conversation: NativeConversationFactory,
    read_context: AssessmentContextReader,
    store: TransferStateStore,
) -> TurnDisposition | None:
    thread_id, turn_id, prompt = event.thread_id, event.turn_id, event.text
    reconciled = reconcile(
        event,
        expected_submission=expected_submission,
        audit=audit,
        conversation=conversation,
        read_context=read_context,
        store=store,
    )
    if not isinstance(reconciled, ReconciledSubmission):
        return reconciled
    pending = reconciled.pending_transfer
    handoff_snapshot = reconciled.snapshot
    profile_context_turn_id = reconciled.profile_context_turn_id
    profile_context_state = reconciled.profile_context_state
    fresh_session = reconciled.fresh_session
    try:
        request = read_context(event)
    except ContextUnavailable as error:
        capability = error.reason_code
        if (
            prompt.strip() in CONTROL_PROMPTS
            or not fresh_session
            or pending is not None
            or (profile_context_state is not None)
            or (capability is None)
        ):
            raise
        with store.transaction(
            thread_id, nonblocking=True, operation="prompt_submit", turn_id=turn_id
        ) as slot:
            current = slot.load()
            if slot.unsafe() or (current is not None and current != handoff_snapshot):
                raise RuntimeError(
                    "Session capability fallback cannot replace handoff state"
                )
            blocked = blocking_recommendation(
                event,
                recommendations=recommendations,
            )
            if blocked is not None:
                audit(
                    thread_id,
                    turn_id,
                    "auto_capability_blocked_recommendation",
                    {
                        "hook_event": "UserPromptSubmit",
                        "reason_code": "known_blocking_recommendation",
                    },
                )
                return blocked
            switch_lifecycle.admit(slot, turn_id)
        audit(
            thread_id,
            turn_id,
            "auto_session_unavailable",
            {"hook_event": "UserPromptSubmit", "reason_code": capability},
        )
        return TurnNotice(
            "Model Fit: this chat's context is unavailable for assessment; profile suitability is unknown and the current profile has been retained."
        )
    with store.transaction(
        thread_id, nonblocking=True, operation="prompt_submit", turn_id=turn_id
    ) as slot:
        manual_evidence = load_blocking_recommendation(
            thread_id, recommendations=recommendations
        )
        current = slot.load()
        if (
            fresh_session
            and (not slot.unsafe())
            and (current == handoff_snapshot)
            and (current is None or current["phase"] == "submitted")
            and (manual_evidence is not None)
            and (manual_evidence["active_profile"] != request["active_profile"])
        ):
            recommendations.clear(thread_id)
            manual_evidence = None
    request = restore_work_context(
        event, request, reconciled, conversation=conversation
    )
    result = assessor(request)
    audit(
        thread_id,
        turn_id,
        "auto_assessed",
        {
            "hook_event": "UserPromptSubmit",
            "triage_decision": result["decision"],
            **(
                {"reason_code": "evaluator_abstained"}
                if result["decision"] == "unknown"
                else {}
            ),
            "active_model": request["active_profile"]["model"],
            "active_effort": request["active_profile"]["effort"],
            "recommended_model": result.get("recommended_model"),
            "recommended_effort": result.get("recommended_effort"),
            "task_sha256": codec.prompt_digest(request["task"]),
            "context_sha256": codec.prompt_digest((request.get("context") or "")),
            "input_sha256": codec.input_digest(request["input"])
            if "input" in request
            else None,
            "assessment_generation": str(expected_submission.generation)
            if expected_submission is not None
            else None,
            "root_session_id": event.session_id or thread_id,
        },
    )
    return apply_decision(
        event,
        request,
        result,
        pending=pending,
        handoff_snapshot=handoff_snapshot,
        manual_evidence=manual_evidence,
        profile_context_turn_id=profile_context_turn_id,
        profile_context_state=profile_context_state,
        expected_submission=expected_submission,
        audit=audit,
        recommendations=recommendations,
        clock=clock,
        conversation=conversation,
        store=store,
    )
