from __future__ import annotations
from vector_prime.application.handoff.guards.receipt import (
    accepted_content,
    require_receipt_identity,
)
from vector_prime.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from vector_prime.application.handoff.types.reconciliation import (
    ReconciledHandoff,
    ReconciliationDenied,
    TransferContinued,
)
from vector_prime.application.handoff.control_message import CONTROL_PROMPTS
from vector_prime.application.switch.types.audit import AuditWriter
from vector_prime.application.assessment.types.execution import AssessmentContextReader
from vector_prime.application.submission.types.input import SubmissionInput
from vector_prime.application.handoff.types.replay import (
    ReplayBound,
    OwnerProfileChanged,
    InputChanged,
)
from vector_prime.application.handoff.types.accepted_input import AcceptedNativeInput
from vector_prime.application.handoff.guards.authorization import require_queue_executor
from vector_prime.application.handoff.guards.authorization import (
    require_transfer_profile,
)
from vector_prime.application.handoff.types.progress import TransferInputEvidence
from vector_prime.application.handoff.guards.authorization import (
    require_preparation_state,
)
from vector_prime.application.handoff.guards.continuation import (
    require_accepted_replay,
    require_control_state,
    require_replay_turn,
)
from vector_prime.application.handoff.guards.queue import (
    require_release_state,
)
from vector_prime.application.assessment.types.decision import AssessmentDecision
from vector_prime.application.assessment.types.profile import ActiveProfile
from vector_prime.application.handoff.types.plan import (
    ManualHandoff,
    TransferTarget,
)
from vector_prime.application.assessment.decoding import required_text
from vector_prime.application.handoff.types.preparation import (
    TransferPreparation,
    TransferContinuation,
)
from vector_prime.application.handoff.types.instruction import TransferInstruction
from vector_prime.application.handoff.helpers.instruction import transfer_instruction
from vector_prime.application.switch.types.state import ProcessSnapshot
from vector_prime.application.switch.types.storage import TransferStateSlot
from vector_prime.application.submission.helpers import content as codec
from vector_prime.application.handoff.helpers.progress import (
    prepared_handoff,
    replay_evidence,
    queued_handoff,
)
from vector_prime.application.handoff.types.progress import (
    AcceptedHandoff,
    AttemptedHandoff,
)
from vector_prime.application.handoff.types.queue import QueueConfirmation

from vector_prime.application.handoff.errors.queue_rejection import NativeQueueRejection
from typing import Callable
from vector_prime.application.handoff.types.queue_storage import QueueStore
from vector_prime.application.handoff.types.clock import Clock


def _transfer_target(
    result: AssessmentDecision, active: ActiveProfile, *, child_agent: bool
) -> TransferTarget | ManualHandoff:
    if child_agent:
        return ManualHandoff(
            "child_profile_allocation_required",
            " Automatic child-agent handoff is not performed; pass the recommendation to the parent agent to choose the profile when allocating the work.",
            retain_profile_context=False,
        )
    if result.get("recommended_speed") not in (None, active["speed"]):
        return ManualHandoff(
            "speed_switch_unsupported",
            f" Automatic speed-tier handoff is unavailable; requested value: {result['recommended_speed']}.",
        )
    target = TransferTarget(
        result.get("recommended_model") or result["active_model"],
        result.get("recommended_effort") or result["active_effort"],
    )
    if (target.model, target.effort) == (
        result["active_model"],
        result["active_effort"],
    ):
        return ManualHandoff("no_model_or_effort_change")
    return target


def authorize_transfer(
    slot: TransferStateSlot, state: ProcessSnapshot, now: float
) -> None:
    prepared_handoff(state)
    slot.save_transition({**state, "transfer_authorized_at": now})


def stage(
    slot: TransferStateSlot, preparation: TransferPreparation
) -> TransferInstruction:
    current = slot.load()
    require_preparation_state(current)
    state: ProcessSnapshot = {
        "phase": "ready",
        "created_at": preparation["created_at"],
        "source_turn_id": preparation["source_turn_id"],
        "prompt": preparation["prompt"],
        "prompt_digest": preparation["prompt_digest"],
        "target_model": preparation["target_model"],
        "target_effort": preparation["target_effort"],
        "official_source_url": required_text(preparation["official_source_url"]),
        "official_guidance": required_text(preparation["official_guidance"]),
        "task_inference": required_text(preparation["task_inference"]),
    }
    if "control_turn_id" in preparation:
        state["control_turn_id"] = preparation["control_turn_id"]
    if "continuation_turn_ids" in preparation:
        state["continuation_turn_ids"] = preparation["continuation_turn_ids"]
    return transfer_instruction(slot.save_transition(state))


def continue_transfer(
    slot: TransferStateSlot, state: ProcessSnapshot, turn_id: str
) -> None:
    require_control_state(state)
    state["control_turn_id"] = turn_id
    if turn_id != state["source_turn_id"]:
        continuations = state.setdefault("continuation_turn_ids", [])
        if turn_id not in continuations:
            continuations.append(turn_id)
    slot.save_transition(state)


def bind_replay(slot: TransferStateSlot, state: ProcessSnapshot, turn_id: str) -> None:
    queued = queued_handoff(state)
    require_replay_turn(queued, turn_id)
    state.pop("pending_assessment", None)
    state["replay_turn_id"] = turn_id
    slot.save_transition(state)


def release(slot: TransferStateSlot) -> None:
    current = slot.load()
    require_release_state(current)
    pending = current.get("pending_assessment") if current is not None else None
    if pending:
        if pending.turn_id is None:
            raise ValueError("Pending assessment has no source turn")
        slot.save_transition(
            {
                "phase": "submitted",
                "source_turn_id": pending.turn_id,
                "pending_assessment": pending,
            },
        )
    else:
        slot.clear()


def enqueue(
    thread_id: str,
    turn_id: str,
    *,
    caller_thread: str | None,
    clock: Clock,
    conversation: NativeConversationFactory,
    store: QueueStore,
    working_directory: Callable[[], str],
) -> QueueConfirmation:
    require_queue_executor(caller_thread, thread_id)
    with store.queue(thread_id, turn_id) as slot:
        prepared = slot.prepare(turn_id, clock())
        if isinstance(prepared, QueueConfirmation):
            return prepared
        with conversation(working_directory()) as app:
            require_transfer_profile(prepared.transfer, app.profile(thread_id))
            content = app.handoff_input(thread_id, prepared.source)
            attempt = AttemptedHandoff(
                prepared.transfer.source_turn_id,
                prepared.transfer.target,
                turn_id,
                TransferInputEvidence("native_input", codec.input_digest(content)),
            )
            slot.write_attempt(
                attempt,
                codec.prompt_digest(codec.input_text(content)),
                codec.prompt_digest(codec.hook_prompt(content)),
            )
            submission = app.enqueue(thread_id, attempt.client_message_id, content)
            if isinstance(submission, NativeQueueRejection):
                slot.reject()
                raise submission.error
            slot.write_receipt_id(submission.submission_id)
            digest = codec.input_digest(accepted_content(submission))
            slot.write_accepted_digest(digest)
            require_receipt_identity(submission)
            accepted = AcceptedHandoff(
                attempt.source_turn_id,
                attempt.target,
                submission.submission_id,
                TransferInputEvidence("native_input", digest),
            )
        slot.confirm(accepted, int(clock()))
        return QueueConfirmation(accepted.submission_id)


def plan_transfer(
    result: AssessmentDecision,
    active: ActiveProfile,
    *,
    child_agent: bool,
    thread_id: str,
    working_directory: str | None,
    conversation: NativeConversationFactory,
) -> TransferTarget | ManualHandoff:
    plan = _transfer_target(result, active, child_agent=child_agent)
    if isinstance(plan, TransferTarget):
        try:
            with conversation(working_directory) as app:
                app.queued_ids(thread_id)
        except (OSError, ValueError, RuntimeError, TimeoutError):
            return ManualHandoff(
                "queue_preflight_unavailable", " The automatic queue is unavailable."
            )
    return plan


def prepare(
    slot: TransferStateSlot,
    *,
    turn_id: str,
    prompt: str,
    target: TransferTarget,
    decision: AssessmentDecision,
    timestamp: float,
    continuation: TransferContinuation | None,
) -> TransferInstruction:
    preparation: TransferPreparation = {
        "created_at": int(timestamp),
        "source_turn_id": turn_id,
        "prompt": prompt,
        "prompt_digest": codec.prompt_digest(prompt),
        "target_model": target.model,
        "target_effort": target.effort,
        "official_source_url": decision["official_source_url"],
        "official_guidance": decision["official_guidance"],
        "task_inference": decision["task_inference"],
    }
    if continuation is not None:
        preparation["source_turn_id"] = continuation.source_turn_id
        preparation["prompt"] = continuation.prompt
        preparation["prompt_digest"] = continuation.prompt_digest
        preparation["control_turn_id"] = turn_id
        preparation["continuation_turn_ids"] = list(continuation.continuation_turn_ids)
        if (
            turn_id != preparation["source_turn_id"]
            and turn_id not in preparation["continuation_turn_ids"]
        ):
            preparation["continuation_turn_ids"].append(turn_id)
    return stage(slot, preparation)


def reconcile(
    slot: TransferStateSlot,
    event: SubmissionInput,
    prior: ProcessSnapshot,
    *,
    audit: AuditWriter,
    conversation: NativeConversationFactory,
    read_context: AssessmentContextReader,
) -> ReconciledHandoff | ReconciliationDenied | TransferContinued | ReplayBound | None:
    thread_id, turn_id, prompt = event.thread_id, event.turn_id, event.text
    pending = None
    if prior["phase"] == "attempting":
        return ReconciliationDenied(
            "Model Fit: the previous queue submission has an unknown outcome; submitting it again is forbidden.",
            "queue_outcome_unknown",
        )
    if prior["phase"] == "rejected":
        if prior["source_turn_id"] == turn_id:
            return ReconciliationDenied(
                "Model Fit: the technical turn ended with a queue rejection; send a new instruction in a separate turn.",
                "queue_rejected_same_turn",
            )
        release(slot)
    if prior["phase"] == "ready":
        if prior.get("pending_assessment") is not None or (
            prompt.strip() not in CONTROL_PROMPTS
            and (
                turn_id != prior["source_turn_id"]
                or codec.prompt_digest(prompt) != prior["prompt_digest"]
            )
        ):
            pending = TransferContinuation(
                prior["source_turn_id"],
                prior["prompt"],
                prior["prompt_digest"],
                tuple(prior.get("continuation_turn_ids", [])),
            )
        else:
            continue_transfer(slot, prior, turn_id)
            audit(thread_id, turn_id, "auto_handoff_continued")
            return TransferContinued()
    elif prior["phase"] == "queued":
        if "queued_client_message_id" in prior:
            return ReconciliationDenied(
                "Model Fit: the assess command verifies the accepted continuation against native client identity."
            )
        if prior.get("replay_turn_id") == turn_id:
            audit(thread_id, turn_id, "auto_steer")
            return None
        if prior["source_turn_id"] == turn_id:
            return ReconciliationDenied(
                "Model Fit: the technical turn already queued the request; send a new instruction in a separate turn.",
                "source_turn_already_queued",
            )
        if prior.get(
            "queued_hook_prompt_digest", prior.get("queued_prompt_digest")
        ) == codec.prompt_digest(prompt):
            if prior.get("replay_turn_id") not in (None, turn_id):
                return ReconciliationDenied(
                    "Model Fit: repeating the request continuation is forbidden.",
                    "duplicate_replay",
                )
            with conversation(event.working_directory) as app:
                if prior["queued_submission_id"] in app.queued_ids(thread_id):
                    return ReconciliationDenied(
                        "Model Fit: the continuation is still queued.",
                        "replay_still_queued",
                    )
            selected = read_context(event)["active_profile"]
            if (selected["model"], selected["effort"]) != (
                prior["target_model"],
                prior["target_effort"],
            ):
                return ReconciliationDenied(
                    "Model Fit: the queued request arrived on the wrong profile.",
                    "replay_wrong_profile",
                )
            bind_replay(slot, prior, turn_id)
            return ReplayBound()
        with conversation(event.working_directory) as app:
            if prior["queued_submission_id"] in app.queued_ids(thread_id):
                deleted = app.delete(thread_id, prior["queued_submission_id"])
                if not deleted:
                    return ReconciliationDenied(
                        "Model Fit: the previous request is starting; repeat the new instruction after it completes.",
                        "prior_replay_starting",
                    )
            elif not app.replay_finished(thread_id, replay_evidence(prior)):
                if prior.get(
                    "replay_turn_id"
                ) is not None or not app.source_terminal_without_replay(
                    thread_id, prior["source_turn_id"], turn_id
                ):
                    return ReconciliationDenied(
                        "Model Fit: the previous request is running; repeat the new instruction after it completes.",
                        "prior_replay_running",
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
        release(slot)
    return ReconciledHandoff(pending)


def reconcile_accepted(
    slot: TransferStateSlot,
    state: ProcessSnapshot,
    *,
    turn_id: str,
    accepted: AcceptedNativeInput,
    profile: ActiveProfile,
    queued_ids: set[str],
) -> ReplayBound | OwnerProfileChanged | InputChanged:
    require_accepted_replay(state, queued_ids)
    same_source = accepted.client_message_id == state.get(
        "queued_client_message_id", state["source_turn_id"]
    )
    same_profile = (profile["model"], profile["effort"]) == (
        state["target_model"],
        state["target_effort"],
    )
    unchanged = codec.input_digest(accepted.content) == state.get("queued_input_digest")
    if same_source and same_profile and unchanged:
        bind_replay(slot, state, turn_id)
        return ReplayBound()
    release(slot)
    if not same_profile:
        return OwnerProfileChanged(same_source)
    return InputChanged(same_source)
