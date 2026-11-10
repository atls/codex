from __future__ import annotations

from model_fit.application.switch.types.audit import AuditWriter
from model_fit.application.switch.types.disposition import (
    BlockedTurn,
)


def block_prompt(
    thread_id: str,
    turn_id: str,
    reason_code: str,
    reason: str,
    phase: str,
    *,
    audit: AuditWriter,
) -> BlockedTurn:
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
    return BlockedTurn(reason)
