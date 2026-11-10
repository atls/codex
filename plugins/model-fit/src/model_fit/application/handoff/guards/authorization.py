from __future__ import annotations
from model_fit.application.switch.types.state import ProcessSnapshot
from model_fit.application.handoff.exceptions.invalid_handoff import InvalidHandoff
from model_fit.application.handoff.types.progress import PreparedHandoff


def require_preparation_state(state: ProcessSnapshot | None) -> None:
    if state is not None and state["phase"] not in {"passed", "ready", "submitted"}:
        raise RuntimeError("Cannot stage a transfer while queue outcome is pending")


def require_queue_executor(caller_thread: str | None, thread_id: str) -> None:
    if caller_thread and caller_thread != thread_id:
        raise InvalidHandoff("foreign_executor")


def require_transfer_profile(
    prepared: PreparedHandoff, selected: tuple[str | None, str | None]
) -> None:
    if selected != (prepared.target.model, prepared.target.effort):
        raise InvalidHandoff("profile_not_applied")


def preparation_is_current(
    current: ProcessSnapshot | None, expected: ProcessSnapshot
) -> bool:
    if current is None or current["phase"] != "ready":
        return False
    return all(
        (
            current.get("assessment_generation")
            == expected.get("assessment_generation"),
            current["source_turn_id"] == expected["source_turn_id"],
            current.get("target_model") == expected.get("target_model"),
            current.get("target_effort") == expected.get("target_effort"),
            current.get("prompt_digest") == expected.get("prompt_digest"),
        )
    )
