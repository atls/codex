from typing import TypeGuard

from model_fit.autoswitch.state.types.record import (
    HandoffStateRecord,
    PendingAssessmentRecord,
)


def _generation(value: object) -> bool:
    return isinstance(value, str) or type(value) is int


def _profile(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        isinstance(value.get("model"), str)
        and isinstance(value.get("effort"), str)
        and "speed" in value
        and (value["speed"] is None or isinstance(value["speed"], str))
    )


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def pending_record(value: object) -> TypeGuard[PendingAssessmentRecord]:
    if not isinstance(value, dict):
        return False
    strings = (
        "thread_id",
        "turn_id",
        "root_session_id",
        "prompt_hash",
        "status",
        "failure_reason",
    )
    if any(key in value and not isinstance(value[key], str) for key in strings):
        return False
    for key in ("agent_id", "active_model"):
        if key in value and value[key] is not None and not isinstance(value[key], str):
            return False
    if "empty_text" in value and not isinstance(value["empty_text"], bool):
        return False
    return "generation" not in value or _generation(value["generation"])


def handoff_record(value: object) -> TypeGuard[HandoffStateRecord]:
    if not isinstance(value, dict):
        return False
    if value.get("phase") not in {
        "ready",
        "submitted",
        "attempting",
        "queued",
        "rejected",
        "passed",
    }:
        return False
    if not isinstance(value.get("source_turn_id"), str):
        return False
    strings = (
        "control_turn_id",
        "assessment_decision",
        "prompt",
        "prompt_digest",
        "target_model",
        "target_effort",
        "queued_submission_id",
        "queued_client_message_id",
        "source_input_digest",
        "queued_input_digest",
        "queued_prompt_digest",
        "queued_hook_prompt_digest",
        "official_source_url",
        "official_guidance",
        "task_inference",
    )
    if any(key in value and not isinstance(value[key], str) for key in strings):
        return False
    if "continuation_turn_ids" in value and not _strings(
        value["continuation_turn_ids"]
    ):
        return False
    if "assessment_generation" in value and not _generation(
        value["assessment_generation"]
    ):
        return False
    pending = value.get("pending_assessment")
    if pending is not None and not pending_record(pending):
        return False
    replay = value.get("replay_turn_id")
    if replay is not None and not isinstance(replay, str):
        return False
    choice = value.get("profile_context_turn_id")
    if choice is not None and not isinstance(choice, str):
        return False
    for key in ("native_profile", "assessed_profile"):
        if key in value and not _profile(value[key]):
            return False
    for key in ("created_at", "queued_at"):
        if key in value and type(value[key]) is not int:
            return False
    if "transfer_authorized_at" in value and not isinstance(
        value["transfer_authorized_at"], (int, float)
    ):
        return False
    return True
