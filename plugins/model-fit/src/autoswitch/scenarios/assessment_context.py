from model_fit.assessment.types.request import ProfileAssessmentInput
from model_fit.autoswitch.types.reconciliation import ReconciledAssessment
from model_fit.autoswitch.handoff.types.conversation import NativeConversationFactory
from model_fit.submission.types.input import SubmissionInput
from model_fit.native_input import codec


def restore_work_context(
    event: SubmissionInput,
    request: ProfileAssessmentInput,
    reconciled: ReconciledAssessment,
    *,
    conversation: NativeConversationFactory,
) -> ProfileAssessmentInput:
    thread_id, turn_id = event.thread_id, event.turn_id
    pending = reconciled.pending_transfer
    profile_context_turn_id = reconciled.profile_context_turn_id
    profile_context_state = reconciled.profile_context_state
    if profile_context_turn_id is not None and profile_context_state is not None:
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
                clarification = codec.input_text(
                    app.source_input(
                        thread_id, profile_context_turn_id, include_steering=True
                    )
                )
        request["context"] = (
            label + clarification + "\n\n" + (request.get("context") or "")
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
            + (request.get("context") or "")
        )[:20000]
    return request
