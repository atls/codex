from vector_prime.entrypoints.hooks.types.output import HookOutput
from vector_prime.application.handoff.guards.authorization import preparation_is_current
from vector_prime.application.switch.types.storage import TransferStateStore
from vector_prime.application.switch.types.audit import AuditWriter
from vector_prime.application.switch.types.disposition import (
    PreparedTransfer,
    TurnDisposition,
)
from vector_prime.entrypoints.hooks.presentation import (
    HookPresentation,
    render_disposition,
)


def deliver_disposition(
    result: TurnDisposition | None, *, store: TransferStateStore, audit: AuditWriter
) -> HookOutput | None:
    output = render_disposition(result)
    if isinstance(result, PreparedTransfer) and not preparation_is_current(
        store.snapshot(result.thread_id), result.instruction
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
