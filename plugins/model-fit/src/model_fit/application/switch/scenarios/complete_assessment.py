from __future__ import annotations

from model_fit.application.handoff import lifecycle as handoff_lifecycle
from model_fit.application.handoff.types.plan import (
    ManualHandoff,
    TransferTarget,
)
from model_fit.application.switch.lifecycle import (
    profile_choice as profile_choice_lifecycle,
)
from model_fit.application.switch.lifecycle import submission as submission_lifecycle


from model_fit.application.assessment.types.decision import AssessmentDecision
from model_fit.application.assessment.types.request import ProfileAssessmentInput
from model_fit.application.assessment.constraints.decision import RECOMMENDATIONS
from model_fit.application.handoff.types.preparation import TransferPreparation
from model_fit.application.switch.denial import block_prompt
from model_fit.application.switch.types.audit import AuditWriter
from model_fit.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.application.switch.state.types.record import HandoffStateRecord
from model_fit.application.submission.helpers import content as codec
from model_fit.application.assessment.types.state import PendingAssessmentRecord
from model_fit.application.switch.types.disposition import (
    ContinueWork,
    ManualRecommendation,
    PreparedTransfer,
    TurnDisposition,
    WorkContext,
)
from model_fit.application.switch.disposition import assessment_disposition

from model_fit.application.submission.types.input import SubmissionInput
from model_fit.application.assessment.types.recommendation import (
    RecommendationRecord,
)
from model_fit.application.assessment.types.cache import (
    ResultCache,
)
from model_fit.application.switch.state.types.storage import TransferStateStore
from model_fit.application.switch.admission.recommendation import (
    blocking_recommendation,
)
from model_fit.application.assessment.lifecycle import load_blocking_recommendation
from model_fit.application.switch.admission.recommendation import (
    retain_manual_recommendation,
)
from model_fit.application.handoff.types.clock import Clock


def complete_assessment(
    event: SubmissionInput,
    request: ProfileAssessmentInput,
    result: AssessmentDecision,
    *,
    pending: HandoffStateRecord | None,
    handoff_snapshot: HandoffStateRecord | None,
    manual_evidence: RecommendationRecord | None,
    profile_context_turn_id: str | None,
    profile_context_state: HandoffStateRecord | None,
    expected_submission: PendingAssessmentRecord | None = None,
    audit: AuditWriter,
    recommendations: ResultCache,
    clock: Clock,
    conversation: NativeConversationFactory,
    store: TransferStateStore,
) -> TurnDisposition | None:
    thread_id, turn_id, prompt = (event.thread_id, event.turn_id, event.text)
    if result["decision"] == "unknown":
        with store.transaction(
            thread_id, operation="prompt_submit", turn_id=turn_id
        ) as slot:
            submission_lifecycle.require_submission(slot, expected_submission)
            current_handoff = slot.load()
            if current_handoff != handoff_snapshot:
                return block_prompt(
                    thread_id,
                    turn_id,
                    "handoff_changed_during_triage",
                    "Model Fit: the handoff state changed while the new request was being assessed.",
                    current_handoff["phase"] if current_handoff else "missing",
                    audit=audit,
                )
            current_manual = load_blocking_recommendation(
                thread_id, recommendations=recommendations
            )
            if current_manual != manual_evidence:
                raise RuntimeError("Blocking recommendation changed during triage")
            if current_manual is not None:
                recommendations.clear(thread_id)
            profile_choice_lifecycle.admit(
                slot, turn_id, "unknown", profile_context_turn_id
            )
        if pending is not None:
            audit(
                thread_id,
                turn_id,
                "auto_handoff_cancelled",
                {
                    "hook_event": "assessment",
                    "reason_code": "pending_reassessed_unknown",
                    "state_phase": "passed",
                },
            )
        return assessment_disposition(result)
    if result["decision"] == "keep":
        with store.transaction(
            thread_id, operation="prompt_submit", turn_id=turn_id
        ) as slot:
            submission_lifecycle.require_submission(slot, expected_submission)
            current_handoff = slot.load()
            if current_handoff != handoff_snapshot:
                return block_prompt(
                    thread_id,
                    turn_id,
                    "handoff_changed_during_triage",
                    "Model Fit: the handoff state changed while the new request was being assessed.",
                    current_handoff["phase"] if current_handoff else "missing",
                    audit=audit,
                )
            current_manual = load_blocking_recommendation(
                thread_id, recommendations=recommendations
            )
            if current_manual != manual_evidence:
                raise RuntimeError("Blocking recommendation changed during triage")
            if current_manual is not None:
                blocked = blocking_recommendation(
                    event,
                    recommendations=recommendations,
                )
                if blocked is not None:
                    if not prompt.strip() or current_manual[
                        "prompt_hash"
                    ] == codec.prompt_digest(""):
                        return blocked
                    if (
                        current_manual["prompt_hash"] == codec.prompt_digest(prompt)
                        and current_manual["active_profile"]
                        == request["active_profile"]
                    ):
                        recommendations.clear(thread_id)
            if pending is not None:
                profile_context_turn_id = turn_id
            profile_choice_lifecycle.admit(
                slot, turn_id, result["decision"], profile_context_turn_id
            )
        if pending is not None:
            audit(
                thread_id,
                turn_id,
                "auto_handoff_cancelled",
                {
                    "hook_event": "UserPromptSubmit",
                    "reason_code": "pending_reassessed_" + result["decision"],
                    "state_phase": "passed",
                },
            )
            return ContinueWork(WorkContext.TRANSFER_CANCELLED)
        return None
    if result["decision"] not in RECOMMENDATIONS:
        raise ValueError("Unsupported triage decision")
    child_agent = event.session_id is not None and event.session_id != thread_id
    plan = handoff_lifecycle.plan_transfer(
        result, request["active_profile"], child_agent=child_agent
    )
    if isinstance(plan, TransferTarget):
        try:
            with conversation(event.working_directory) as app:
                app.queued_ids(thread_id)
        except (OSError, ValueError, RuntimeError, TimeoutError):
            plan = ManualHandoff(
                "queue_preflight_unavailable", " The automatic queue is unavailable."
            )
    if isinstance(plan, ManualHandoff):
        if plan.retain_profile_context and profile_context_state is not None:
            with store.transaction(
                thread_id, operation="prompt_submit", turn_id=turn_id
            ) as slot:
                submission_lifecycle.require_submission(slot, expected_submission)
                if slot.load() != profile_context_state:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "profile_choice_changed_during_triage",
                        "Model Fit: the retained profile choice changed during assessment.",
                        "passed",
                        audit=audit,
                    )
                profile_choice_lifecycle.admit(
                    slot, turn_id, profile_context_turn_id=profile_context_turn_id
                )
        audit(
            thread_id,
            turn_id,
            "auto_fallback",
            {
                "hook_event": "assessment" if child_agent else "UserPromptSubmit",
                "reason_code": plan.reason_code,
            },
        )
        return retain_manual_recommendation(
            event,
            request,
            result,
            ManualRecommendation(result, plan.explanation),
            expected_submission=expected_submission,
            recommendations=recommendations,
            store=store,
        )
    target_model, target_effort = plan.model, plan.effort
    state: TransferPreparation = {
        "created_at": int(clock()),
        "source_turn_id": turn_id,
        "prompt": prompt,
        "prompt_digest": codec.prompt_digest(prompt),
        "target_model": target_model,
        "target_effort": target_effort,
        "official_source_url": result["official_source_url"],
        "official_guidance": result["official_guidance"],
        "task_inference": result["task_inference"],
    }
    with store.transaction(
        thread_id, operation="prompt_submit", turn_id=turn_id
    ) as slot:
        submission_lifecycle.require_submission(slot, expected_submission)
        current_handoff = slot.load()
        if current_handoff != handoff_snapshot:
            return block_prompt(
                thread_id,
                turn_id,
                "handoff_changed_during_triage",
                "Model Fit: the handoff state or retained profile choice changed while the new request was being assessed.",
                current_handoff["phase"] if current_handoff else "missing",
                audit=audit,
            )
        if pending is not None:
            state["source_turn_id"] = pending["source_turn_id"]
            state["prompt"] = pending["prompt"]
            state["prompt_digest"] = pending["prompt_digest"]
            state["control_turn_id"] = turn_id
            state["continuation_turn_ids"] = list(
                pending.get("continuation_turn_ids", [])
            )
            if (
                turn_id != state["source_turn_id"]
                and turn_id not in state["continuation_turn_ids"]
            ):
                state["continuation_turn_ids"].append(turn_id)
            audit(thread_id, turn_id, "auto_handoff_continued")
        prepared_state = handoff_lifecycle.stage(slot, state)
    return PreparedTransfer(thread_id, turn_id, prepared_state)
