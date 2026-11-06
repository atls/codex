"""Persist and restore a blocking manual profile recommendation."""

from __future__ import annotations

from typing import Any

from model_fit.application.assessment.validation import validated_active_profile
from model_fit.application.handoff.dependencies import Dependencies

from .lifecycle import Lifecycle
from .requests.prompt import Prompt


def recommended_profile(pending: dict[str, Any]) -> dict[str, Any]:
    active = pending["active_profile"]
    result = pending["result"]
    return {
        field: result.get(f"recommended_{field}") or active[field]
        for field in ("model", "effort", "speed")
    }


def load_blocking_recommendation(
    thread_id: str, *, dependencies: Dependencies
) -> dict[str, Any] | None:
    if dependencies.cache.unsafe(thread_id):
        raise ValueError("Blocking recommendation cannot be a symlink")
    cached = dependencies.cache.load(thread_id)
    if cached is None:
        return None
    if (
        len(cached["prompt_hash"]) != 64
        or len(bytes.fromhex(cached["prompt_hash"])) != 32
        or cached["prompt_hash"] != cached["prompt_hash"].lower()
    ):
        raise ValueError("Blocking recommendation input hash is invalid")
    active = validated_active_profile({"active_profile": cached["active_profile"]})
    if (
        not active["model"]
        or not active["effort"]
        or any(
            (
                f"active_{field}" not in cached["result"]
                or cached["result"][f"active_{field}"] != active[field]
                for field in active
            )
        )
    ):
        raise ValueError("Blocking recommendation profile is inconsistent")
    output = dependencies.presentation.hook_output(cached["result"])
    if output is None or not dependencies.presentation.is_block(output):
        raise ValueError("Blocking recommendation is unavailable")
    return cached


def blocking_recommendation(
    event: Prompt,
    *,
    dependencies: Dependencies,
    prompt_hash: str | None = None,
    empty_input: bool | None = None,
) -> dict[str, Any] | None:
    cached = load_blocking_recommendation(event.thread_id, dependencies=dependencies)
    if cached is None:
        return None
    active = cached["active_profile"]
    output = dependencies.presentation.hook_output(cached["result"])
    unknown_input = (
        not event.text.strip() if empty_input is None else empty_input
    ) or cached["prompt_hash"] == dependencies.input.prompt_digest("")
    same_input = cached["prompt_hash"] == (
        prompt_hash or dependencies.input.prompt_digest(event.text)
    )
    return (
        output
        if active["model"] == event.active_model and (same_input or unknown_input)
        else None
    )


def retain_manual_recommendation(
    event: Prompt,
    request: dict[str, Any],
    result: dict[str, Any],
    output: dict[str, Any],
    *,
    dependencies: Dependencies,
    expected_submission: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with dependencies.state.transaction(
        event.thread_id,
        nonblocking=True,
        operation="prompt_submit",
        turn_id=event.turn_id,
    ) as slot:
        Lifecycle.require_submission(slot, expected_submission)
        current = slot.load()
        submitted = (
            current is not None
            and current["phase"] == "submitted"
            and current.get("pending_assessment", {}).get("turn_id") == event.turn_id
        )
        if (
            current is None
            or submitted
            or (
                current["phase"] == "passed"
                and current["source_turn_id"] == event.turn_id
            )
        ):
            dependencies.cache.save(
                event.thread_id, {**request, "task": event.text}, result
            )
    return output
