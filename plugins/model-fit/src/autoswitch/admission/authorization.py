from __future__ import annotations

from model_fit.autoswitch.lifecycle import handoff as handoff_lifecycle


from model_fit.autoswitch.state.types.record import HandoffStateRecord

from model_fit.autoswitch.admission.types.result import (
    AllowedTool,
    DeniedTool,
    ToolAdmission,
)

from model_fit.native_input.types.json import JsonValue

from model_fit.autoswitch.types.audit import AuditWriter
from model_fit.autoswitch.state.types.storage import TransferStateStore
from model_fit.autoswitch.admission.types.input import ToolAdmissionInput
from model_fit.autoswitch.handoff.types.clock import Clock


def authorize_transfer(
    event: ToolAdmissionInput,
    state: HandoffStateRecord,
    bound: dict[str, JsonValue] | None,
    *,
    audit: AuditWriter,
    clock: Clock,
    store: TransferStateStore,
) -> ToolAdmission:
    try:
        with store.transaction(
            event.thread_id,
            nonblocking=True,
            operation="pre_tool_use",
            turn_id=event.turn_id,
        ) as slot:
            if slot.load() == state:
                handoff_lifecycle.authorize_transfer(slot, state, clock())
                if bound is not None:
                    audit(
                        event.thread_id,
                        event.turn_id,
                        "auto_transfer_bound",
                        {"hook_event": "PreToolUse"},
                    )
                    return AllowedTool(bound)
                return AllowedTool()
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
    return DeniedTool(
        "Model Fit: handoff state changed or is busy; the previous technical command is not authorized."
    )
