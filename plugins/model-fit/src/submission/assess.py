from __future__ import annotations

from collections.abc import Callable
from typing import Any

from model_fit.autoswitch.state import transitions
from model_fit.autoswitch.exceptions.superseded import AssessmentSuperseded
from model_fit.autoswitch.exceptions.unavailable import SubmissionUnavailable
from model_fit.autoswitch.handoff.prepare import prepare
from model_fit.submission.evaluation import AssessmentRunner
from model_fit.autoswitch.audit import AuditWriter
from model_fit.submission.evaluation import AssessmentContextReader
from model_fit.autoswitch.handoff.conversation import (
    NativeConversationFactory,
)
from model_fit.autoswitch.handoff.input_reader import NativeInputReader
from model_fit.autoswitch.output import HookOutputRenderer
from model_fit.submission.input import SubmissionInput
from model_fit.autoswitch.recommendation.storage import RecommendationStore
from model_fit.autoswitch.state.storage import TransferStateStore
from model_fit.autoswitch.recommendation.check import blocking_recommendation
from model_fit.autoswitch.handoff.clock import Clock


def assess_submitted(
    decode: Callable[[dict[str, Any], str], SubmissionInput],
    *,
    assessor: AssessmentRunner,
    assessment_failure: tuple[type[Exception], ...],
    audit: AuditWriter,
    recommendations: RecommendationStore,
    caller_thread: str | None,
    clock: Clock,
    context_failure: type[Exception],
    context_reason: Callable[[Exception, str], str | None],
    inputs: NativeInputReader,
    conversation: NativeConversationFactory,
    presentation: HookOutputRenderer,
    read_context: AssessmentContextReader,
    store: TransferStateStore,
) -> dict[str, Any]:
    try:
        thread_id = caller_thread
        if not thread_id:
            raise SubmissionUnavailable(None, "native_thread_required")
        with store.transaction(thread_id, operation="assessment") as slot:
            state = slot.load()
            if state is None:
                raise SubmissionUnavailable(thread_id, "submission_missing")
            pending = state.get("pending_assessment")
            if pending is None:
                if state["phase"] == "ready":
                    return presentation.control_context(
                        thread_id, state["source_turn_id"], state
                    )
                if state["phase"] == "queued":
                    if state.get("replay_turn_id") is not None:
                        return presentation.context(presentation.replay_context)
                    return presentation.queued_context()
                if state.get("assessment_decision") == "keep":
                    return presentation.assessed()
                return presentation.warning(
                    "Model Fit: no new assessment was performed; suitability is unknown."
                )
            if pending["status"] == "running":
                return presentation.warning(
                    "Model Fit: assessment is already running; wait for the first invocation's result."
                )
            pending = transitions.start_assessment(slot)
        event = decode(pending, "")
        if event.thread_id != thread_id:
            raise ValueError("Submitted input belongs to another Codex thread")
        try:
            try:
                request = read_context(event)
            except context_failure as error:
                capability = context_reason(error, thread_id)
                if (
                    capability is None
                    or state["phase"] not in {"submitted", "passed"}
                    or state.get("profile_context_turn_id") is not None
                ):
                    raise
                with store.transaction(
                    thread_id,
                    nonblocking=True,
                    operation="assessment",
                    turn_id=event.turn_id,
                ) as slot:
                    current = slot.load()
                    transitions.require_submission(slot, pending)
                    blocked = blocking_recommendation(
                        event,
                        prompt_hash=pending["prompt_hash"],
                        empty_input=pending["empty_text"],
                        recommendations=recommendations,
                        inputs=inputs,
                        presentation=presentation,
                    )
                    if blocked is not None:
                        recommendations.clear(thread_id)
                    transitions.admit(slot, event.turn_id, "unknown")
                    transitions.finish_assessment(slot, pending)
                audit(
                    thread_id,
                    event.turn_id,
                    "auto_session_unavailable",
                    {"hook_event": "assessment", "reason_code": capability},
                )
                audit(
                    thread_id,
                    event.turn_id,
                    "auto_unknown",
                    {"hook_event": "assessment"},
                )
                return presentation.unknown(
                    "Native chat context is unavailable for assessment."
                )
            else:
                with conversation(event.working_directory) as app:
                    accepted = app.accepted_input(thread_id, event.turn_id)
                    queued = (
                        app.queued_ids(thread_id)
                        if state["phase"] == "queued"
                        else set()
                    )
                event = decode(pending, inputs.hook_prompt(accepted.source_content))
                request = {
                    **request,
                    "task": inputs.hook_prompt(accepted.content) or request["task"],
                }
                if (
                    state["phase"] == "passed"
                    and state.get("assessed_profile") is not None
                    and (state["assessed_profile"] != request["active_profile"])
                ):
                    with store.transaction(
                        thread_id, operation="assessment", turn_id=event.turn_id
                    ) as slot:
                        transitions.require_submission(slot, pending)
                        transitions.admit(
                            slot,
                            event.turn_id,
                            "native_override",
                            event.turn_id,
                            native_profile=request["active_profile"],
                        )
                    audit(
                        thread_id,
                        event.turn_id,
                        "auto_native_profile_override",
                        {
                            "hook_event": "assessment",
                            "reason_code": "native_choice_after_keep",
                        },
                    )
                if state["phase"] == "queued":
                    matches = accepted.client_message_id == state.get(
                        "queued_client_message_id", state["source_turn_id"]
                    )
                    with store.transaction(
                        thread_id, operation="assessment", turn_id=event.turn_id
                    ) as slot:
                        current = slot.load()
                        transitions.require_submission(slot, pending)
                        if state["queued_submission_id"] in queued:
                            raise RuntimeError(
                                "Previous native submission is still queued"
                            )
                        unchanged = inputs.input_digest(accepted.content) == state.get(
                            "queued_input_digest"
                        )
                        if matches and (
                            request["active_profile"]["model"],
                            request["active_profile"]["effort"],
                        ) != (state["target_model"], state["target_effort"]):
                            transitions.consume_submission(slot, event.turn_id, pending)
                            transitions.admit(
                                slot,
                                event.turn_id,
                                "native_override",
                                event.turn_id,
                                native_profile=request["active_profile"],
                            )
                            transitions.finish_assessment(slot, pending)
                            audit(
                                thread_id, event.turn_id, "auto_native_profile_override"
                            )
                            return presentation.context(
                                "Model Fit: the native owner changed the profile after queueing. The current profile is retained; its suitability was not reassessed here. Perform the current original request with all current attachments and annotations."
                            )
                        if matches and unchanged:
                            transitions.bind_replay(slot, current, event.turn_id)
                            audit(thread_id, event.turn_id, "auto_replay")
                            return presentation.context(presentation.replay_context)
                        transitions.consume_submission(slot, event.turn_id, pending)
                        if not matches and (
                            request["active_profile"]["model"],
                            request["active_profile"]["effort"],
                        ) != (state["target_model"], state["target_effort"]):
                            transitions.admit(
                                slot,
                                event.turn_id,
                                "native_override",
                                event.turn_id,
                                native_profile=request["active_profile"],
                            )
                            audit(
                                thread_id,
                                event.turn_id,
                                "auto_native_profile_override",
                                {
                                    "hook_event": "assessment",
                                    "reason_code": "native_choice_before_new_message",
                                },
                            )
                    audit(
                        thread_id,
                        event.turn_id,
                        "auto_native_input_changed"
                        if matches
                        else "auto_native_queue_detached",
                    )
                request = {**request, "input": accepted.content}
                output = prepare(
                    event,
                    expected_submission=pending,
                    assessor=assessor,
                    audit=audit,
                    recommendations=recommendations,
                    clock=clock,
                    context_failure=context_failure,
                    context_reason=context_reason,
                    inputs=inputs,
                    conversation=conversation,
                    presentation=presentation,
                    read_context=lambda _: request,
                    store=store,
                )
                with conversation(event.working_directory) as app:
                    current_model, current_effort = app.profile(thread_id)
                if not isinstance(current_model, str) or not isinstance(
                    current_effort, str
                ):
                    raise ValueError("Native profile unavailable after assessment")
                if (current_model, current_effort) != (
                    request["active_profile"]["model"],
                    request["active_profile"]["effort"],
                ):
                    selected = {
                        **request["active_profile"],
                        "model": current_model,
                        "effort": current_effort,
                    }
                    with store.transaction(
                        thread_id, operation="assessment", turn_id=event.turn_id
                    ) as slot:
                        current = slot.load()
                        if (
                            current is None
                            or current.get("assessment_generation")
                            != pending["generation"]
                        ):
                            raise AssessmentSuperseded(
                                thread_id, event.turn_id, pending["generation"]
                            )
                        if current["phase"] not in {"ready", "passed", "submitted"}:
                            raise RuntimeError(
                                "Native choice cannot discard unresolved transfer"
                            )
                        cached = recommendations.load(thread_id)
                        if (
                            cached is not None
                            and cached["active_profile"] == request["active_profile"]
                            and (
                                cached["prompt_hash"]
                                == inputs.prompt_digest(event.text)
                            )
                        ):
                            recommendations.clear(thread_id)
                        transitions.admit(
                            slot,
                            event.turn_id,
                            "native_override",
                            event.turn_id,
                            native_profile=selected,
                        )
                        transitions.finish_assessment(
                            slot, pending, assessed_profile=selected
                        )
                    audit(
                        thread_id,
                        event.turn_id,
                        "auto_native_profile_override",
                        {
                            "hook_event": "assessment",
                            "reason_code": "native_choice_during_assessment",
                        },
                    )
                    return presentation.context(
                        "Model Fit: the native owner changed the profile during assessment. The previous recommendation is cancelled; the current choice is retained and its suitability is unknown. Perform the original request with its current attachments."
                    )
            with store.transaction(
                thread_id, operation="assessment", turn_id=event.turn_id
            ) as slot:
                current = slot.load()
                if (
                    current is None
                    or current.get("assessment_generation") != pending["generation"]
                ):
                    raise AssessmentSuperseded(
                        thread_id, event.turn_id, pending["generation"]
                    )
                if output is not None and presentation.is_block(output):
                    transitions.fail_assessment(slot, pending)
                else:
                    transitions.finish_assessment(
                        slot, pending, assessed_profile=request["active_profile"]
                    )
            audit(
                thread_id,
                event.turn_id,
                presentation.prompt_outcome(output),
                {
                    "hook_event": "assessment",
                    "assessment_generation": str(pending["generation"]),
                    "root_session_id": event.session_id or thread_id,
                },
            )
            return output if output is not None else presentation.assessed()
        except AssessmentSuperseded:
            raise
        except Exception as error:
            if isinstance(error, assessment_failure):
                try:
                    with store.transaction(
                        thread_id,
                        nonblocking=True,
                        operation="assessment",
                        turn_id=event.turn_id,
                    ) as slot:
                        continued = transitions.abstain_assessment(slot, pending)
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
                    return presentation.unknown(
                        "The evaluator is unavailable (" + type(error).__name__ + ")."
                    )
            try:
                with store.transaction(
                    thread_id,
                    nonblocking=True,
                    operation="assessment",
                    turn_id=event.turn_id,
                ) as slot:
                    transitions.fail_assessment(
                        slot, pending, reason="assessment_failed"
                    )
            except BlockingIOError:
                pass
            raise
    except AssessmentSuperseded as error:
        audit(
            error.thread_id,
            error.turn_id,
            "auto_assessment_superseded",
            {
                "hook_event": "assessment",
                "reason_code": "newer_submission",
                "assessment_generation": error.generation,
            },
        )
        return presentation.context(
            "The previous Model Fit assessment was superseded and not applied. Use the instruction for the latest accepted input; do not repeat a handoff based on the cancelled assessment."
        )
