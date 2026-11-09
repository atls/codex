from __future__ import annotations

from typing import Any

from model_fit.autoswitch import transitions
from model_fit.autoswitch.interfaces.audit import AuditWriter
from model_fit.autoswitch.interfaces.presentation import HookOutputRenderer
from model_fit.autoswitch.interfaces.store import TransferStateStore
from model_fit.autoswitch.interfaces.tool_check import ToolAdmissionInput
from model_fit.autoswitch.types.clock import Clock


def authorize_transfer(
    event: ToolAdmissionInput,
    state: dict[str, Any],
    bound: dict[str, Any] | None,
    *,
    audit: AuditWriter,
    clock: Clock,
    presentation: HookOutputRenderer,
    store: TransferStateStore,
) -> dict[str, Any] | None:
    try:
        with store.transaction(
            event.thread_id,
            nonblocking=True,
            operation="pre_tool_use",
            turn_id=event.turn_id,
        ) as slot:
            if slot.load() == state:
                transitions.authorize_transfer(slot, state, clock())
                if bound is not None:
                    audit(
                        event.thread_id,
                        event.turn_id,
                        "auto_transfer_bound",
                        {"hook_event": "PreToolUse"},
                    )
                    return presentation.allow_tool(bound)
                return None
        reason = "transfer_state_changed"
    except BlockingIOError:
        reason = "state_lock_busy"
    audit(
        event.thread_id,
        event.turn_id,
        "auto_guard_block",
        {
            "hook_event": "PreToolUse",
            "reason_code": reason,
            "state_phase": state["phase"],
        },
    )
    return presentation.deny_tool(
        "Model Fit: handoff state changed or is busy; the previous technical command is not authorized."
    )
