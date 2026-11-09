from __future__ import annotations

from model_fit.autoswitch.types.protocols.audit import AuditWriter
from model_fit.autoswitch.types.protocols.output import HookOutputRenderer


def block_prompt(
    thread_id: str,
    turn_id: str,
    reason_code: str,
    reason: str,
    phase: str,
    *,
    audit: AuditWriter,
    presentation: HookOutputRenderer,
) -> dict[str, str]:
    audit(
        thread_id,
        turn_id,
        "auto_prompt_block",
        {
            "hook_event": "UserPromptSubmit",
            "reason_code": reason_code,
            "state_phase": phase,
        },
    )
    return presentation.block(reason)
