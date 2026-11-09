from __future__ import annotations

from typing import Any, Callable

from model_fit.autoswitch.state import transitions
from model_fit.autoswitch.assessment_outcome import apply_assessment
from model_fit.autoswitch.denial import block_prompt
from model_fit.submission.types.evaluation import AssessmentRunner
from model_fit.autoswitch.types.audit import AuditWriter
from model_fit.submission.types.evaluation import AssessmentContextReader
from model_fit.autoswitch.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.autoswitch.handoff.types.input_reader import NativeInputReader
from model_fit.autoswitch.state.types.record import PendingAssessmentRecord
from model_fit.autoswitch.types.output import HookOutputRenderer
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


def prepare(
    event: SubmissionInput,
    *,
    expected_submission: PendingAssessmentRecord | None = None,
    assessor: AssessmentRunner,
    audit: AuditWriter,
    recommendations: RecommendationStore,
    clock: Clock,
    context_failure: type[Exception],
    context_reason: Callable[[Exception, str], str | None],
    inputs: NativeInputReader,
    conversation: NativeConversationFactory,
    presentation: HookOutputRenderer,
    read_context: AssessmentContextReader,
    store: TransferStateStore,
) -> dict[str, Any] | None:
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
        transitions.require_submission(slot, expected_submission)
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
                transitions.release(slot)
            prior = None
        if prior is not None:
            if prior["phase"] == "attempting":
                return block_prompt(
                    thread_id,
                    turn_id,
                    "queue_outcome_unknown",
                    "Model Fit: the previous queue submission has an unknown outcome; submitting it again is forbidden.",
                    prior["phase"],
                    audit=audit,
                    presentation=presentation,
                )
            if prior["phase"] == "rejected":
                if prior["source_turn_id"] == turn_id:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "queue_rejected_same_turn",
                        "Model Fit: the technical turn ended with a queue rejection; send a new instruction in a separate turn.",
                        prior["phase"],
                        audit=audit,
                        presentation=presentation,
                    )
                transitions.release(slot)
            if prior["phase"] == "ready":
                if prior.get("pending_assessment") is not None or (
                    prompt.strip() not in presentation.control_prompts
                    and (
                        turn_id != prior["source_turn_id"]
                        or inputs.prompt_digest(prompt) != prior["prompt_digest"]
                    )
                ):
                    pending = prior
                else:
                    transitions.continue_transfer(slot, prior, turn_id)
                    audit(thread_id, turn_id, "auto_handoff_continued")
                    return presentation.control_context(thread_id, turn_id, prior)
            elif prior["phase"] == "queued":
                if "queued_client_message_id" in prior:
                    return presentation.block(
                        "Model Fit: the assess command verifies the accepted continuation against native client identity."
                    )
                if prior.get("replay_turn_id") == turn_id:
                    audit(thread_id, turn_id, "auto_steer")
                    return None
                if prior["source_turn_id"] == turn_id:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "source_turn_already_queued",
                        "Model Fit: the technical turn already queued the request; send a new instruction in a separate turn.",
                        prior["phase"],
                        audit=audit,
                        presentation=presentation,
                    )
                if prior.get(
                    "queued_hook_prompt_digest", prior.get("queued_prompt_digest")
                ) == inputs.prompt_digest(prompt):
                    if prior.get("replay_turn_id") not in (None, turn_id):
                        return block_prompt(
                            thread_id,
                            turn_id,
                            "duplicate_replay",
                            "Model Fit: repeating the request continuation is forbidden.",
                            prior["phase"],
                            audit=audit,
                            presentation=presentation,
                        )
                    with conversation(event.working_directory) as app:
                        if prior["queued_submission_id"] in app.queued_ids(thread_id):
                            return block_prompt(
                                thread_id,
                                turn_id,
                                "replay_still_queued",
                                "Model Fit: the continuation is still queued.",
                                prior["phase"],
                                audit=audit,
                                presentation=presentation,
                            )
                    selected = read_context(event)["active_profile"]
                    if (selected["model"], selected["effort"]) != (
                        prior["target_model"],
                        prior["target_effort"],
                    ):
                        return block_prompt(
                            thread_id,
                            turn_id,
                            "replay_wrong_profile",
                            "Model Fit: the queued request arrived on the wrong profile.",
                            prior["phase"],
                            audit=audit,
                            presentation=presentation,
                        )
                    transitions.bind_replay(slot, prior, turn_id)
                    return presentation.context(presentation.replay_context)
                with conversation(event.working_directory) as app:
                    if prior["queued_submission_id"] in app.queued_ids(thread_id):
                        deleted = app.delete(thread_id, prior["queued_submission_id"])
                        if not deleted:
                            return block_prompt(
                                thread_id,
                                turn_id,
                                "prior_replay_starting",
                                "Model Fit: the previous request is starting; repeat the new instruction after it completes.",
                                prior["phase"],
                                audit=audit,
                                presentation=presentation,
                            )
                    elif not app.replay_finished(thread_id, prior):
                        if prior.get(
                            "replay_turn_id"
                        ) is not None or not app.source_terminal_without_replay(
                            thread_id, prior["source_turn_id"], turn_id
                        ):
                            return block_prompt(
                                thread_id,
                                turn_id,
                                "prior_replay_running",
                                "Model Fit: the previous request is running; repeat the new instruction after it completes.",
                                prior["phase"],
                                audit=audit,
                                presentation=presentation,
                            )
                        audit(
                            thread_id,
                            turn_id,
                            "auto_handoff_cancelled",
                            {
                                "hook_event": "UserPromptSubmit",
                                "reason_code": "terminal_source_without_replay",
                                "state_phase": "queued",
                            },
                        )
                transitions.release(slot)
        handoff_snapshot = slot.load()
    try:
        request = read_context(event)
    except context_failure as error:
        capability = context_reason(error, thread_id)
        if (
            prompt.strip() in presentation.control_prompts
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
                inputs=inputs,
                presentation=presentation,
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
            transitions.admit(slot, turn_id)
        audit(
            thread_id,
            turn_id,
            "auto_session_unavailable",
            {"hook_event": "UserPromptSubmit", "reason_code": capability},
        )
        return presentation.warning(
            "Model Fit: this chat's context is unavailable for assessment; profile suitability is unknown and the current profile has been retained."
        )
    with store.transaction(
        thread_id, nonblocking=True, operation="prompt_submit", turn_id=turn_id
    ) as slot:
        manual_evidence = load_blocking_recommendation(
            thread_id, recommendations=recommendations, presentation=presentation
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
    if profile_context_turn_id is not None:
        if profile_context_state.get("native_profile") is not None:
            label = (
                "Retained native chat owner's profile choice for the current work:\n"
            )
            if profile_context_turn_id == turn_id:
                clarification = (
                    "When checking the accepted current message, the native profile differs from the previous handoff profile: it is now "
                    + str(profile_context_state["native_profile"])
                    + ". Account for this fresh choice on the current request. Retain it unless the current user message explicitly requests profile reselection or a profile change. This records a choice, not evidence of suitability or a minimum model."
                )
            else:
                clarification = (
                    "After the previous request was queued, the native chat owner changed the profile to "
                    + str(profile_context_state["native_profile"])
                    + ". Retain the selected profile for the same work until the user separately authorizes a change. This records a choice, not an assessment of suitability or a minimum model."
                )
        else:
            label = "Previous user clarification that cancelled the handoff; account for it on the same work:\n"
            with conversation(event.working_directory) as app:
                clarification = inputs.input_text(
                    app.source_input(
                        thread_id, profile_context_turn_id, include_steering=True
                    )
                )
        request["context"] = (
            label + clarification + "\n\n" + request.get("context", "")
        )[:20000]
    if pending is not None:
        if "input" in request:
            with conversation(event.working_directory) as app:
                earlier = app.handoff_input(thread_id, pending)
            request["input"] = (
                earlier
                if turn_id
                in {
                    pending["source_turn_id"],
                    *pending.get("continuation_turn_ids", []),
                }
                else earlier + request["input"]
            )
        request["context"] = (
            "Original unfinished user request:\n"
            + pending["prompt"]
            + "\n\n"
            + request.get("context", "")
        )[:20000]
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
            "task_sha256": inputs.prompt_digest(request["task"]),
            "context_sha256": inputs.prompt_digest(request.get("context", "")),
            "input_sha256": inputs.input_digest(request["input"])
            if "input" in request
            else None,
            "assessment_generation": str(expected_submission["generation"])
            if expected_submission is not None
            else None,
            "root_session_id": event.session_id or thread_id,
        },
    )
    return apply_assessment(
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
        inputs=inputs,
        conversation=conversation,
        presentation=presentation,
        store=store,
    )
