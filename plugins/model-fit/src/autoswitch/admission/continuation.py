from __future__ import annotations

from typing import Any

from model_fit.autoswitch.admission.types.protocols.tools import TransferTools
from model_fit.autoswitch.types.protocols.audit import AuditWriter
from model_fit.autoswitch.types.protocols.output import HookOutputRenderer
from model_fit.autoswitch.admission.types.dataclasses.input import ToolAdmissionInput


def can_continue_admitted_tool(
    event: ToolAdmissionInput,
    state: dict[str, Any] | None,
    *,
    actions: TransferTools,
) -> bool:
    if can_continue_failed_assessment(event, state, actions=actions):
        return True
    if (
        state is None
        or state.get("pending_assessment")
        or (not isinstance(event.turn_id, str))
        or actions.matches_transfer(event)
        or actions.matches_assessment(event)
    ):
        return False
    return (
        state["phase"] == "passed"
        and state["source_turn_id"] == event.turn_id
        or (state["phase"] == "queued" and state.get("replay_turn_id") == event.turn_id)
    )


def guard_replay_transfer(
    event: ToolAdmissionInput,
    state: dict[str, Any] | None,
    *,
    actions: TransferTools,
    audit: AuditWriter,
    presentation: HookOutputRenderer,
) -> dict[str, Any] | None:
    if (
        state is None
        or state["phase"] != "queued"
        or state.get("replay_turn_id") != event.turn_id
        or (not actions.matches_transfer(event))
    ):
        return None
    audit(
        event.thread_id,
        event.turn_id,
        "auto_guard_block",
        {
            "hook_event": "PreToolUse",
            "reason_code": "replay_transfer_already_completed",
            "state_phase": "queued",
        },
    )
    return presentation.deny_tool(presentation.replay_context)


def can_continue_failed_assessment(
    event: ToolAdmissionInput,
    state: dict[str, Any] | None,
    *,
    actions: TransferTools,
) -> bool:
    pending = state.get("pending_assessment") if state else None
    return bool(
        state
        and isinstance(event.turn_id, str)
        and event.turn_id
        and (state["phase"] in {"submitted", "passed", "ready"})
        and pending
        and (pending.get("turn_id") == event.turn_id)
        and (pending.get("status") == "failed")
        and (pending.get("failure_reason") == "assessment_failed")
        and (not actions.matches_transfer(event))
        and (not actions.matches_assessment(event))
    )
