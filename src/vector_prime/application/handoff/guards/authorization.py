from vector_prime.application.handoff.exceptions.invalid_handoff import InvalidHandoff
from vector_prime.application.handoff.types.progress import PreparedHandoff


def require_queue_executor(caller_thread: str | None, thread_id: str) -> None:
    if caller_thread and caller_thread != thread_id:
        raise InvalidHandoff("foreign_executor")


def require_transfer_profile(
    prepared: PreparedHandoff, selected: tuple[str | None, str | None]
) -> None:
    if selected != (prepared.target.model, prepared.target.effort):
        raise InvalidHandoff("profile_not_applied")
