from model_fit.application.handoff.dependencies import Dependencies


def block_prompt(
    thread_id: str,
    turn_id: str,
    reason_code: str,
    reason: str,
    phase: str,
    *,
    dependencies: Dependencies,
) -> dict[str, str]:
    dependencies.audit(
        thread_id,
        turn_id,
        "auto_prompt_block",
        {
            "hook_event": "UserPromptSubmit",
            "reason_code": reason_code,
            "state_phase": phase,
        },
    )
    return dependencies.presentation.block(reason)
