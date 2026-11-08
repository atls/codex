from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Callable

from model_fit.assessment.validation import RECOMMENDATIONS
from model_fit.autoswitch import transitions
from model_fit.autoswitch.denial import block_prompt
from model_fit.autoswitch.ports.conversation import Conversation
from model_fit.autoswitch.ports.inputs import Inputs
from model_fit.autoswitch.ports.presentation import Presentation
from model_fit.autoswitch.ports.recommendations import Recommendations
from model_fit.autoswitch.ports.store import Store
from model_fit.autoswitch.recommendation import (
    blocking_recommendation,
    load_blocking_recommendation,
    retain_manual_recommendation,
)
from model_fit.autoswitch.requests.prompt import Prompt


def apply_assessment(
    event: Prompt,
    request: dict[str, Any],
    result: dict[str, Any],
    *,
    pending: dict[str, Any] | None,
    handoff_snapshot: dict[str, Any] | None,
    manual_evidence: dict[str, Any] | None,
    profile_context_turn_id: str | None,
    profile_context_state: dict[str, Any] | None,
    expected_submission: dict[str, Any] | None = None,
    audit: Callable[..., Any],
    recommendations: Recommendations,
    clock: Callable[[], float],
    inputs: Inputs,
    conversation: Callable[[object], AbstractContextManager[Conversation]],
    presentation: Presentation,
    store: Store,
) -> dict[str, Any] | None:
    thread_id, turn_id, prompt = (event.thread_id, event.turn_id, event.text)
    if result["decision"] == "unknown":
        with store.transaction(
            thread_id, operation="prompt_submit", turn_id=turn_id
        ) as slot:
            transitions.require_submission(slot, expected_submission)
            if slot.load() != handoff_snapshot:
                return block_prompt(
                    thread_id,
                    turn_id,
                    "handoff_changed_during_triage",
                    "Model Fit: состояние переноса изменилось во время проверки нового запроса.",
                    slot.load()["phase"] if slot.load() else "missing",
                    audit=audit,
                    presentation=presentation,
                )
            current_manual = load_blocking_recommendation(
                thread_id, recommendations=recommendations, presentation=presentation
            )
            if current_manual != manual_evidence:
                raise RuntimeError("Blocking recommendation changed during triage")
            if current_manual is not None:
                recommendations.clear(thread_id)
            transitions.admit(slot, turn_id, "unknown", profile_context_turn_id)
        if pending is not None:
            audit(
                thread_id,
                turn_id,
                "auto_handoff_cancelled",
                {
                    "hook_event": "assessment",
                    "reason_code": "pending_reassessed_unknown",
                    "state_phase": "passed",
                },
            )
        return presentation.hook_output(result)
    if result["decision"] == "keep":
        with store.transaction(
            thread_id, operation="prompt_submit", turn_id=turn_id
        ) as slot:
            transitions.require_submission(slot, expected_submission)
            current_handoff = slot.load()
            if current_handoff != handoff_snapshot:
                return block_prompt(
                    thread_id,
                    turn_id,
                    "handoff_changed_during_triage",
                    "Model Fit: состояние переноса изменилось во время проверки нового запроса.",
                    current_handoff["phase"] if current_handoff else "missing",
                    audit=audit,
                    presentation=presentation,
                )
            current_manual = load_blocking_recommendation(
                thread_id, recommendations=recommendations, presentation=presentation
            )
            if current_manual != manual_evidence:
                raise RuntimeError("Blocking recommendation changed during triage")
            if current_manual is not None:
                blocked = blocking_recommendation(
                    event,
                    recommendations=recommendations,
                    inputs=inputs,
                    presentation=presentation,
                )
                if blocked is not None and result["decision"] == "keep":
                    if not prompt.strip() or current_manual[
                        "prompt_hash"
                    ] == inputs.prompt_digest(""):
                        return blocked
                    if (
                        current_manual["prompt_hash"] == inputs.prompt_digest(prompt)
                        and current_manual["active_profile"]
                        == request["active_profile"]
                    ):
                        recommendations.clear(thread_id)
            if pending is not None and result["decision"] == "keep":
                profile_context_turn_id = turn_id
            transitions.admit(
                slot, turn_id, result["decision"], profile_context_turn_id
            )
        if pending is not None:
            audit(
                thread_id,
                turn_id,
                "auto_handoff_cancelled",
                {
                    "hook_event": "UserPromptSubmit",
                    "reason_code": "pending_reassessed_" + result["decision"],
                    "state_phase": "passed",
                },
            )
            output = (
                None
                if result["decision"] == "keep"
                else presentation.hook_output(result)
            )
            output = presentation.with_context(
                output, presentation.handoff_cancelled_context
            )
            return output
        return (
            None if result["decision"] == "keep" else presentation.hook_output(result)
        )
    if result["decision"] not in RECOMMENDATIONS:
        raise ValueError("Unsupported triage decision")
    manual = presentation.hook_output(result)
    if event.session_id is not None and event.session_id != thread_id:
        presentation.extend_reason(
            manual,
            " Автоматический перенос дочернего агента не выполняется; передай рекомендацию родительскому агенту для выбора профиля при выделении работы.",
        )
        audit(
            thread_id,
            turn_id,
            "auto_fallback",
            {
                "hook_event": "assessment",
                "reason_code": "child_profile_allocation_required",
            },
        )
        return retain_manual_recommendation(
            event,
            request,
            result,
            manual,
            expected_submission=expected_submission,
            recommendations=recommendations,
            store=store,
        )
    target_model = result.get("recommended_model") or result["active_model"]
    target_effort = result.get("recommended_effort") or result["active_effort"]
    if result.get("recommended_speed") not in (
        None,
        request["active_profile"]["speed"],
    ):
        presentation.extend_reason(
            manual,
            f" Автоматический перенос скорости недоступен; целевое значение: {result['recommended_speed']}.",
        )
        if profile_context_state is not None:
            with store.transaction(
                thread_id, operation="prompt_submit", turn_id=turn_id
            ) as slot:
                transitions.require_submission(slot, expected_submission)
                if slot.load() != profile_context_state:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "profile_choice_changed_during_triage",
                        "Model Fit: сохранённый выбор профиля изменился во время проверки запроса.",
                        "passed",
                        audit=audit,
                        presentation=presentation,
                    )
                transitions.admit(
                    slot, turn_id, profile_context_turn_id=profile_context_turn_id
                )
        audit(
            thread_id,
            turn_id,
            "auto_fallback",
            {
                "hook_event": "UserPromptSubmit",
                "reason_code": "speed_switch_unsupported",
            },
        )
        return retain_manual_recommendation(
            event,
            request,
            result,
            manual,
            expected_submission=expected_submission,
            recommendations=recommendations,
            store=store,
        )
    if (target_model, target_effort) == (
        result["active_model"],
        result["active_effort"],
    ):
        if profile_context_state is not None:
            with store.transaction(
                thread_id, operation="prompt_submit", turn_id=turn_id
            ) as slot:
                transitions.require_submission(slot, expected_submission)
                if slot.load() != profile_context_state:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "profile_choice_changed_during_triage",
                        "Model Fit: сохранённый выбор профиля изменился во время проверки запроса.",
                        "passed",
                        audit=audit,
                        presentation=presentation,
                    )
                transitions.admit(
                    slot, turn_id, profile_context_turn_id=profile_context_turn_id
                )
        audit(
            thread_id,
            turn_id,
            "auto_fallback",
            {
                "hook_event": "UserPromptSubmit",
                "reason_code": "no_model_or_effort_change",
            },
        )
        return retain_manual_recommendation(
            event,
            request,
            result,
            manual,
            expected_submission=expected_submission,
            recommendations=recommendations,
            store=store,
        )
    try:
        with conversation(event.working_directory) as app:
            app.queued_ids(thread_id)
    except (OSError, ValueError, RuntimeError, TimeoutError):
        presentation.extend_reason(manual, " Автоматическая очередь недоступна.")
        if profile_context_state is not None:
            with store.transaction(
                thread_id, operation="prompt_submit", turn_id=turn_id
            ) as slot:
                transitions.require_submission(slot, expected_submission)
                if slot.load() != profile_context_state:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "profile_choice_changed_during_triage",
                        "Model Fit: сохранённый выбор профиля изменился во время проверки запроса.",
                        "passed",
                        audit=audit,
                        presentation=presentation,
                    )
                transitions.admit(
                    slot, turn_id, profile_context_turn_id=profile_context_turn_id
                )
        audit(
            thread_id,
            turn_id,
            "auto_fallback",
            {
                "hook_event": "UserPromptSubmit",
                "reason_code": "queue_preflight_unavailable",
            },
        )
        return retain_manual_recommendation(
            event,
            request,
            result,
            manual,
            expected_submission=expected_submission,
            recommendations=recommendations,
            store=store,
        )
    state = {
        "created_at": int(clock()),
        "source_turn_id": turn_id,
        "prompt": prompt,
        "prompt_digest": inputs.prompt_digest(prompt),
        "target_model": target_model,
        "target_effort": target_effort,
        "official_source_url": result["official_source_url"],
        "official_guidance": result["official_guidance"],
        "task_inference": result["task_inference"],
    }
    with store.transaction(
        thread_id, operation="prompt_submit", turn_id=turn_id
    ) as slot:
        transitions.require_submission(slot, expected_submission)
        current_handoff = slot.load()
        if current_handoff != handoff_snapshot:
            return block_prompt(
                thread_id,
                turn_id,
                "handoff_changed_during_triage",
                "Model Fit: состояние переноса или сохранённый выбор профиля изменились во время проверки нового запроса.",
                current_handoff["phase"] if current_handoff else "missing",
                audit=audit,
                presentation=presentation,
            )
        if pending is not None:
            state["source_turn_id"] = pending["source_turn_id"]
            state["prompt"] = pending["prompt"]
            state["prompt_digest"] = pending["prompt_digest"]
            state["control_turn_id"] = turn_id
            state["continuation_turn_ids"] = list(
                pending.get("continuation_turn_ids", [])
            )
            if (
                turn_id != state["source_turn_id"]
                and turn_id not in state["continuation_turn_ids"]
            ):
                state["continuation_turn_ids"].append(turn_id)
            audit(thread_id, turn_id, "auto_handoff_continued")
        transitions.stage(slot, state)
    return presentation.control_context(thread_id, turn_id, state)
