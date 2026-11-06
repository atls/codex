"""Opt-in Desktop Model Fit handoff to a queued turn on the selected profile."""

from __future__ import annotations

from typing import Any

from model_fit.application.assessment.validation import RECOMMENDATIONS
from model_fit.application.handoff.denial import block_prompt
from model_fit.application.handoff.dependencies import Dependencies
from model_fit.application.handoff.recommendation import (
    blocking_recommendation,
    load_blocking_recommendation,
    retain_manual_recommendation,
)

from .lifecycle import Lifecycle
from .requests.prompt import Prompt


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
    dependencies: Dependencies,
    expected_submission: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    thread_id, turn_id, prompt = (event.thread_id, event.turn_id, event.text)
    if result["decision"] == "unknown":
        with dependencies.state.transaction(
            thread_id, operation="prompt_submit", turn_id=turn_id
        ) as slot:
            Lifecycle.require_submission(slot, expected_submission)
            if slot.load() != handoff_snapshot:
                return block_prompt(
                    thread_id,
                    turn_id,
                    "handoff_changed_during_triage",
                    "Model Fit: состояние переноса изменилось во время проверки нового запроса.",
                    slot.load()["phase"] if slot.load() else "missing",
                    dependencies=dependencies,
                )
            current_manual = load_blocking_recommendation(
                thread_id, dependencies=dependencies
            )
            if current_manual != manual_evidence:
                raise RuntimeError("Blocking recommendation changed during triage")
            if current_manual is not None:
                dependencies.cache.clear(thread_id)
            Lifecycle.admit(slot, turn_id, "unknown", profile_context_turn_id)
        if pending is not None:
            dependencies.audit(
                thread_id,
                turn_id,
                "auto_handoff_cancelled",
                {
                    "hook_event": "assessment",
                    "reason_code": "pending_reassessed_unknown",
                    "state_phase": "passed",
                },
            )
        return dependencies.presentation.hook_output(result)
    if result["decision"] == "keep":
        with dependencies.state.transaction(
            thread_id, operation="prompt_submit", turn_id=turn_id
        ) as slot:
            Lifecycle.require_submission(slot, expected_submission)
            current_handoff = slot.load()
            if current_handoff != handoff_snapshot:
                return block_prompt(
                    thread_id,
                    turn_id,
                    "handoff_changed_during_triage",
                    "Model Fit: состояние переноса изменилось во время проверки нового запроса.",
                    current_handoff["phase"] if current_handoff else "missing",
                    dependencies=dependencies,
                )
            current_manual = load_blocking_recommendation(
                thread_id, dependencies=dependencies
            )
            if current_manual != manual_evidence:
                raise RuntimeError("Blocking recommendation changed during triage")
            if current_manual is not None:
                blocked = blocking_recommendation(event, dependencies=dependencies)
                if blocked is not None and result["decision"] == "keep":
                    if not prompt.strip() or current_manual[
                        "prompt_hash"
                    ] == dependencies.input.prompt_digest(""):
                        return blocked
                    if (
                        current_manual["prompt_hash"]
                        == dependencies.input.prompt_digest(prompt)
                        and current_manual["active_profile"]
                        == request["active_profile"]
                    ):
                        dependencies.cache.clear(thread_id)
            if pending is not None and result["decision"] == "keep":
                profile_context_turn_id = turn_id
            Lifecycle.admit(slot, turn_id, result["decision"], profile_context_turn_id)
        if pending is not None:
            dependencies.audit(
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
                else dependencies.presentation.hook_output(result)
            )
            output = dependencies.presentation.with_context(
                output, dependencies.presentation.handoff_cancelled_context
            )
            return output
        return (
            None
            if result["decision"] == "keep"
            else dependencies.presentation.hook_output(result)
        )
    if result["decision"] not in RECOMMENDATIONS:
        raise ValueError("Unsupported triage decision")
    manual = dependencies.presentation.hook_output(result)
    if event.session_id is not None and event.session_id != thread_id:
        dependencies.presentation.extend_reason(
            manual,
            " Автоматический перенос дочернего агента не выполняется; передай рекомендацию родительскому агенту для выбора профиля при выделении работы.",
        )
        dependencies.audit(
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
            dependencies=dependencies,
            expected_submission=expected_submission,
        )
    target_model = result.get("recommended_model") or result["active_model"]
    target_effort = result.get("recommended_effort") or result["active_effort"]
    if result.get("recommended_speed") not in (
        None,
        request["active_profile"]["speed"],
    ):
        dependencies.presentation.extend_reason(
            manual,
            f" Автоматический перенос скорости недоступен; целевое значение: {result['recommended_speed']}.",
        )
        if profile_context_state is not None:
            with dependencies.state.transaction(
                thread_id, operation="prompt_submit", turn_id=turn_id
            ) as slot:
                Lifecycle.require_submission(slot, expected_submission)
                if slot.load() != profile_context_state:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "profile_choice_changed_during_triage",
                        "Model Fit: сохранённый выбор профиля изменился во время проверки запроса.",
                        "passed",
                        dependencies=dependencies,
                    )
                Lifecycle.admit(
                    slot, turn_id, profile_context_turn_id=profile_context_turn_id
                )
        dependencies.audit(
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
            dependencies=dependencies,
            expected_submission=expected_submission,
        )
    if (target_model, target_effort) == (
        result["active_model"],
        result["active_effort"],
    ):
        if profile_context_state is not None:
            with dependencies.state.transaction(
                thread_id, operation="prompt_submit", turn_id=turn_id
            ) as slot:
                Lifecycle.require_submission(slot, expected_submission)
                if slot.load() != profile_context_state:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "profile_choice_changed_during_triage",
                        "Model Fit: сохранённый выбор профиля изменился во время проверки запроса.",
                        "passed",
                        dependencies=dependencies,
                    )
                Lifecycle.admit(
                    slot, turn_id, profile_context_turn_id=profile_context_turn_id
                )
        dependencies.audit(
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
            dependencies=dependencies,
            expected_submission=expected_submission,
        )
    try:
        with dependencies.native(event.working_directory) as app:
            app.queued_ids(thread_id)
    except (OSError, ValueError, RuntimeError, TimeoutError):
        dependencies.presentation.extend_reason(
            manual, " Автоматическая очередь недоступна."
        )
        if profile_context_state is not None:
            with dependencies.state.transaction(
                thread_id, operation="prompt_submit", turn_id=turn_id
            ) as slot:
                Lifecycle.require_submission(slot, expected_submission)
                if slot.load() != profile_context_state:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "profile_choice_changed_during_triage",
                        "Model Fit: сохранённый выбор профиля изменился во время проверки запроса.",
                        "passed",
                        dependencies=dependencies,
                    )
                Lifecycle.admit(
                    slot, turn_id, profile_context_turn_id=profile_context_turn_id
                )
        dependencies.audit(
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
            dependencies=dependencies,
            expected_submission=expected_submission,
        )
    state = {
        "created_at": int(dependencies.clock()),
        "source_turn_id": turn_id,
        "prompt": prompt,
        "prompt_digest": dependencies.input.prompt_digest(prompt),
        "target_model": target_model,
        "target_effort": target_effort,
        "official_source_url": result["official_source_url"],
        "official_guidance": result["official_guidance"],
        "task_inference": result["task_inference"],
    }
    with dependencies.state.transaction(
        thread_id, operation="prompt_submit", turn_id=turn_id
    ) as slot:
        Lifecycle.require_submission(slot, expected_submission)
        current_handoff = slot.load()
        if current_handoff != handoff_snapshot:
            return block_prompt(
                thread_id,
                turn_id,
                "handoff_changed_during_triage",
                "Model Fit: состояние переноса или сохранённый выбор профиля изменились во время проверки нового запроса.",
                current_handoff["phase"] if current_handoff else "missing",
                dependencies=dependencies,
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
            dependencies.audit(thread_id, turn_id, "auto_handoff_continued")
        Lifecycle.stage(slot, state)
    return dependencies.presentation.control_context(thread_id, turn_id, state)
