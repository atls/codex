from __future__ import annotations

from model_fit.application.handoff import lifecycle as handoff_lifecycle
from model_fit.application.switch.lifecycle import submission as submission_lifecycle


from model_fit.application.switch.denial import block_prompt
from model_fit.application.switch.types.audit import AuditWriter
from model_fit.application.assessment.types.execution import AssessmentContextReader
from model_fit.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.application.submission.helpers import content as codec
from model_fit.application.assessment.types.state import PendingAssessmentRecord
from model_fit.application.switch.types.disposition import (
    BlockedTurn,
    ContinueWork,
    PreparedTransfer,
    TurnDisposition,
    WorkContext,
)
from model_fit.application.handoff.control_message import CONTROL_PROMPTS

from model_fit.application.submission.types.input import SubmissionInput
from model_fit.application.switch.state.types.storage import TransferStateStore

from model_fit.application.switch.types.reconciliation import ReconciledAssessment


def reconcile(
    event: SubmissionInput,
    *,
    expected_submission: PendingAssessmentRecord | None,
    audit: AuditWriter,
    conversation: NativeConversationFactory,
    read_context: AssessmentContextReader,
    store: TransferStateStore,
) -> ReconciledAssessment | TurnDisposition | None:
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
        submission_lifecycle.require_submission(slot, expected_submission)
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
            if prior["phase"] == "attempting":
                return block_prompt(
                    thread_id,
                    turn_id,
                    "queue_outcome_unknown",
                    "Model Fit: the previous queue submission has an unknown outcome; submitting it again is forbidden.",
                    prior["phase"],
                    audit=audit,
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
                    )
                handoff_lifecycle.release(slot)
            if prior["phase"] == "ready":
                if prior.get("pending_assessment") is not None or (
                    prompt.strip() not in CONTROL_PROMPTS
                    and (
                        turn_id != prior["source_turn_id"]
                        or codec.prompt_digest(prompt) != prior["prompt_digest"]
                    )
                ):
                    pending = prior
                else:
                    handoff_lifecycle.continue_transfer(slot, prior, turn_id)
                    audit(thread_id, turn_id, "auto_handoff_continued")
                    return PreparedTransfer(thread_id, turn_id, prior)
            elif prior["phase"] == "queued":
                if "queued_client_message_id" in prior:
                    return BlockedTurn(
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
                    )
                if prior.get(
                    "queued_hook_prompt_digest", prior.get("queued_prompt_digest")
                ) == codec.prompt_digest(prompt):
                    if prior.get("replay_turn_id") not in (None, turn_id):
                        return block_prompt(
                            thread_id,
                            turn_id,
                            "duplicate_replay",
                            "Model Fit: repeating the request continuation is forbidden.",
                            prior["phase"],
                            audit=audit,
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
                        )
                    handoff_lifecycle.bind_replay(slot, prior, turn_id)
                    return ContinueWork(WorkContext.REPLAY)
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
                handoff_lifecycle.release(slot)
        handoff_snapshot = slot.load()
    return ReconciledAssessment(
        pending,
        handoff_snapshot,
        profile_context_turn_id,
        profile_context_state,
        fresh_session,
    )
