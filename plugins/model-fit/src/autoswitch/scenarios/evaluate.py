from __future__ import annotations

from model_fit.autoswitch.exceptions.context_unavailable import ContextUnavailable

from model_fit.autoswitch.lifecycle import profile_choice as profile_choice_lifecycle


from model_fit.autoswitch.types.reconciliation import ReconciledAssessment
from model_fit.autoswitch.scenarios.reconcile import reconcile
from model_fit.autoswitch.scenarios.assessment_context import restore_work_context
from model_fit.autoswitch.scenarios.complete_assessment import complete_assessment
from model_fit.submission.types.evaluation import AssessmentRunner
from model_fit.autoswitch.types.audit import AuditWriter
from model_fit.submission.types.evaluation import AssessmentContextReader
from model_fit.autoswitch.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.native_input import codec
from model_fit.autoswitch.state.types.record import PendingAssessmentRecord
from model_fit.autoswitch.types.disposition import (
    TurnDisposition,
    TurnNotice,
)
from model_fit.autoswitch.handoff.control_message import CONTROL_PROMPTS

from model_fit.submission.types.input import SubmissionInput
from model_fit.autoswitch.recommendation.types.storage import (
    RecommendationStore,
)
from model_fit.autoswitch.state.types.storage import TransferStateStore
from model_fit.autoswitch.recommendation.check import (
    blocking_recommendation,
    load_blocking_recommendation,
)
from model_fit.autoswitch.handoff.types.clock import Clock


def evaluate(
    event: SubmissionInput,
    *,
    expected_submission: PendingAssessmentRecord | None = None,
    assessor: AssessmentRunner,
    audit: AuditWriter,
    recommendations: RecommendationStore,
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
    if not isinstance(reconciled, ReconciledAssessment):
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
            profile_choice_lifecycle.admit(slot, turn_id)
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
            "assessment_generation": str(expected_submission["generation"])
            if expected_submission is not None
            else None,
            "root_session_id": event.session_id or thread_id,
        },
    )
    return complete_assessment(
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
