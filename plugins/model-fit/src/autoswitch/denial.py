from __future__ import annotations

from typing import Any, Callable

from model_fit.autoswitch.ports.presentation import Presentation


def block_prompt(
    thread_id: str,
    turn_id: str,
    reason_code: str,
    reason: str,
    phase: str,
    *,
    audit: Callable[..., Any],
    presentation: Presentation,
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
