from model_fit.autoswitch.lifecycle.handoff import preparation_is_current
from model_fit.autoswitch.state.types.storage import TransferStateStore
from model_fit.autoswitch.types.audit import AuditWriter
from model_fit.autoswitch.types.disposition import PreparedTransfer, TurnDisposition
from model_fit.entrypoints.hooks.presentation import (
    HookPresentation,
    render_disposition,
)
from model_fit.native_input.types.json import JsonValue


def deliver_disposition(
    result: TurnDisposition | None, *, store: TransferStateStore, audit: AuditWriter
) -> dict[str, JsonValue] | None:
    output = render_disposition(result)
    if isinstance(result, PreparedTransfer) and not preparation_is_current(
        store.snapshot(result.thread_id), result.state
    ):
        audit(
            result.thread_id,
            result.turn_id,
            "auto_assessment_superseded",
            {"hook_event": "assessment", "reason_code": "newer_submission"},
        )
        return HookPresentation().context(
            "The previous Model Fit assessment was superseded and not applied. Use the instruction for the latest accepted input; do not repeat a handoff based on the cancelled assessment."
        )
    return output
