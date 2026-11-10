from typing_extensions import TypedDict


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
