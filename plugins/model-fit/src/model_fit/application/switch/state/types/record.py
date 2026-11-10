from typing import Literal, Required, TypedDict
from model_fit.application.assessment.types.profile import ActiveProfile


class PendingAssessmentRecord(TypedDict, total=False):
    thread_id: str
    turn_id: str
    root_session_id: str
    agent_id: str | None
    working_directory: str | None
    active_model: str | None
    prompt_hash: str
    empty_text: bool
    status: str
    generation: str | int
    failure_reason: str


class HandoffStateRecord(TypedDict, total=False):
    phase: Required[
        Literal["ready", "submitted", "attempting", "queued", "rejected", "passed"]
    ]
    source_turn_id: Required[str]
    control_turn_id: str
    replay_turn_id: str | None
    continuation_turn_ids: list[str]
    assessment_generation: str | int
    pending_assessment: PendingAssessmentRecord | None
    assessment_decision: str
    profile_context_turn_id: str | None
    native_profile: ActiveProfile
    assessed_profile: ActiveProfile
    queued_at: int
    created_at: int
    transfer_authorized_at: float
    prompt: str
    prompt_digest: str
    target_model: str
    target_effort: str
    queued_submission_id: str
    queued_client_message_id: str
    source_input_digest: str
    queued_input_digest: str
    queued_prompt_digest: str
    queued_hook_prompt_digest: str
    official_source_url: str
    official_guidance: str
    task_inference: str
