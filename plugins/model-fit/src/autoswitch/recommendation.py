from __future__ import annotations

from typing import Any

from model_fit.assessment.validation import validated_active_profile
from model_fit.autoswitch import transitions
from model_fit.autoswitch.interfaces.handoff_state import HandoffStateRecord
from model_fit.autoswitch.interfaces.inputs import NativeInputReader
from model_fit.autoswitch.interfaces.pending_assessment import PendingAssessmentRecord
from model_fit.autoswitch.interfaces.presentation import HookOutputRenderer
from model_fit.autoswitch.interfaces.prompt import SubmissionInput
from model_fit.autoswitch.interfaces.recommendations import RecommendationStore
from model_fit.autoswitch.interfaces.store import TransferStateStore


def recommended_profile(pending: HandoffStateRecord) -> dict[str, Any]:
    active = pending["active_profile"]
    result = pending["result"]
    return {
        field: result.get(f"recommended_{field}") or active[field]
        for field in ("model", "effort", "speed")
    }


def load_blocking_recommendation(
    thread_id: str,
    *,
    recommendations: RecommendationStore,
    presentation: HookOutputRenderer,
) -> dict[str, Any] | None:
    if recommendations.unsafe(thread_id):
        raise ValueError("Blocking recommendation cannot be a symlink")
    cached = recommendations.load(thread_id)
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
    output = presentation.hook_output(cached["result"])
    if output is None or not presentation.is_block(output):
        raise ValueError("Blocking recommendation is unavailable")
    return cached


def blocking_recommendation(
    event: SubmissionInput,
    *,
    prompt_hash: str | None = None,
    empty_input: bool | None = None,
    recommendations: RecommendationStore,
    inputs: NativeInputReader,
    presentation: HookOutputRenderer,
) -> dict[str, Any] | None:
    cached = load_blocking_recommendation(
        event.thread_id, recommendations=recommendations, presentation=presentation
    )
    if cached is None:
        return None
    active = cached["active_profile"]
    output = presentation.hook_output(cached["result"])
    unknown_input = (
        not event.text.strip() if empty_input is None else empty_input
    ) or cached["prompt_hash"] == inputs.prompt_digest("")
    same_input = cached["prompt_hash"] == (
        prompt_hash or inputs.prompt_digest(event.text)
    )
    return (
        output
        if active["model"] == event.active_model and (same_input or unknown_input)
        else None
    )


def retain_manual_recommendation(
    event: SubmissionInput,
    request: dict[str, Any],
    result: dict[str, Any],
    output: dict[str, Any],
    *,
    expected_submission: PendingAssessmentRecord | None = None,
    recommendations: RecommendationStore,
    store: TransferStateStore,
) -> dict[str, Any]:
    with store.transaction(
        event.thread_id,
        nonblocking=True,
        operation="prompt_submit",
        turn_id=event.turn_id,
    ) as slot:
        transitions.require_submission(slot, expected_submission)
        current = slot.load()
        submitted = (
            current is not None
            and current["phase"] == "submitted"
            and (current.get("pending_assessment", {}).get("turn_id") == event.turn_id)
        )
        if (
            current is None
            or submitted
            or (
                current["phase"] == "passed"
                and current["source_turn_id"] == event.turn_id
            )
        ):
            recommendations.save(
                event.thread_id, {**request, "task": event.text}, result
            )
    return output
