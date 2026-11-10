from model_fit.autoswitch.state.types.record import HandoffStateRecord
from model_fit.autoswitch.admission.types.result import (
    AllowedTool,
    DeniedTool,
    ToolAdmission,
)
from model_fit.autoswitch.admission.types.input import ToolAdmissionInput
from model_fit.autoswitch.admission.types.tools import TransferTools
from model_fit.autoswitch.types.audit import AuditWriter
from model_fit.autoswitch.admission.guards.replay import replay_transfer_completed


def deny_replay_transfer(
    event: ToolAdmissionInput,
    state: HandoffStateRecord | None,
    *,
    actions: TransferTools,
    audit: AuditWriter,
    replay_context: str,
) -> ToolAdmission:
    if not replay_transfer_completed(event, state, actions=actions):
        return AllowedTool()
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
    return DeniedTool(replay_context)


def deny_unprepared_transfer(
    event: ToolAdmissionInput,
    state: HandoffStateRecord | None,
    *,
    actions: TransferTools,
    audit: AuditWriter,
    replay_context: str,
) -> ToolAdmission:
    if not actions.matches_transfer(event):
        return AllowedTool()
    audit(
        event.thread_id,
        event.turn_id,
        "auto_guard_block",
        {
            "hook_event": "PreToolUse",
            "reason_code": "transfer_not_prepared_for_turn",
            "state_phase": state["phase"] if state else "missing",
        },
    )
    return DeniedTool(
        "Model Fit: no handoff is prepared for this turn. Do not repeat previous technical commands; ordinary tools are available after assessment of the current input."
    )
