from vector_prime.application.assessment.decoding import required_text
from vector_prime.application.handoff.types.plan import TransferTarget
from vector_prime.application.handoff.types.preparation import (
    TransferContinuation,
    TransferPreparation,
)
from vector_prime.application.handoff.types.progress import (
    PreparedHandoff,
    TransferInputEvidence,
)
from vector_prime.application.handoff.types.state import (
    AttemptingTransfer,
    QueuedTransfer,
    ReadyTransfer,
    RejectedTransfer,
    TransferState,
)
from vector_prime.infrastructure.adapters.filesystem.record import FileRecord
from vector_prime.application.handoff.types.source import HandoffSource
from vector_prime.application.handoff.types.instruction import TransferInstruction


def transfer_state(snapshot: FileRecord | None) -> TransferState | None:
    if snapshot is None:
        return None
    phase, source = snapshot["phase"], snapshot["source_turn_id"]
    continuations = tuple(snapshot.get("continuation_turn_ids", []))
    control = snapshot.get("control_turn_id")
    if phase == "ready":
        prompt, digest = snapshot.get("prompt"), snapshot.get("prompt_digest")
        continuation = (
            TransferContinuation(source, prompt, digest, continuations)
            if prompt is not None and digest is not None
            else None
        )
        target, created = transfer_target(snapshot), snapshot.get("created_at")
        prepared = (
            PreparedHandoff(
                source,
                target,
                created,
                snapshot.get("transfer_authorized_at", created),
                continuation.prompt,
                continuation.prompt_digest,
            )
            if target is not None and created is not None and continuation is not None
            else None
        )
        return ReadyTransfer(
            source,
            snapshot.get("pending_assessment") is not None,
            continuation,
            prepared,
            continuations,
            control,
            read_instruction(snapshot),
        )
    if phase == "queued":
        evidence = None
        if "queued_input_digest" in snapshot:
            evidence = TransferInputEvidence(
                "native_input", snapshot["queued_input_digest"]
            )
        elif "queued_prompt_digest" in snapshot:
            evidence = TransferInputEvidence(
                "legacy_prompt", snapshot["queued_prompt_digest"]
            )
        return QueuedTransfer(
            source,
            snapshot.get("queued_submission_id"),
            snapshot.get("queued_client_message_id"),
            snapshot.get("replay_turn_id"),
            transfer_target(snapshot),
            snapshot.get("created_at", snapshot.get("queued_at")),
            evidence,
            snapshot.get(
                "queued_hook_prompt_digest", snapshot.get("queued_prompt_digest")
            ),
            continuations,
            control,
            handoff_source(snapshot),
            snapshot.get("task_inference"),
        )
    if phase == "rejected":
        return RejectedTransfer(source, control)
    if phase == "attempting":
        return AttemptingTransfer(source, control)
    return None


def transfer_target(snapshot: FileRecord) -> TransferTarget | None:
    model, effort = snapshot.get("target_model"), snapshot.get("target_effort")
    if model is None or effort is None:
        return None
    return TransferTarget(model, effort)


def staged_snapshot(preparation: TransferPreparation) -> FileRecord:
    state: FileRecord = {
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
    return state


def read_instruction(state: FileRecord) -> TransferInstruction | None:
    target = transfer_target(state)
    if target is None:
        return None
    try:
        return TransferInstruction(
            source_turn_id=state["source_turn_id"],
            generation=state.get("assessment_generation"),
            prompt_digest=state["prompt_digest"],
            target=target,
            official_source_url=state["official_source_url"],
            official_guidance=state["official_guidance"],
            task_inference=state["task_inference"],
        )
    except KeyError:
        return None


def handoff_source(state: FileRecord) -> HandoffSource:
    return HandoffSource(
        state["source_turn_id"],
        state.get("prompt"),
        tuple(state.get("continuation_turn_ids", [])),
    )
