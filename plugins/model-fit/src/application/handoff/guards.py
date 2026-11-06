"""Opt-in Desktop Model Fit handoff to a queued turn on the selected profile."""

from __future__ import annotations

from typing import Any

from model_fit.application.handoff.configuration import MAX_REPLAY_EVAL_CHARS
from model_fit.application.handoff.dependencies import Dependencies

from .lifecycle import Lifecycle
from .recommendation import load_blocking_recommendation
from .requests.answer_check import AnswerCheck
from .requests.tool_check import ToolCheck


def can_continue_admitted_tool(
    event: ToolCheck, state: dict[str, Any] | None, *, dependencies: Dependencies
) -> bool:
    if can_continue_failed_assessment(event, state, dependencies=dependencies):
        return True
    if (
        state is None
        or state.get("pending_assessment")
        or not isinstance(event.turn_id, str)
        or dependencies.actions.matches_transfer(event)
        or dependencies.actions.matches_assessment(event)
    ):
        return False
    return (
        state["phase"] == "passed"
        and state["source_turn_id"] == event.turn_id
        or state["phase"] == "queued"
        and state.get("replay_turn_id") == event.turn_id
    )


def guard_replay_transfer(
    event: ToolCheck, state: dict[str, Any] | None, *, dependencies: Dependencies
) -> dict[str, Any] | None:
    if (
        state is None
        or state["phase"] != "queued"
        or state.get("replay_turn_id") != event.turn_id
        or not dependencies.actions.matches_transfer(event)
    ):
        return None
    dependencies.audit(
        event.thread_id,
        event.turn_id,
        "auto_guard_block",
        {
            "hook_event": "PreToolUse",
            "reason_code": "replay_transfer_already_completed",
            "state_phase": "queued",
        },
    )
    return dependencies.presentation.deny_tool(dependencies.presentation.replay_context)


def guard_unprepared_transfer(
    event: ToolCheck, state: dict[str, Any] | None, *, dependencies: Dependencies
) -> dict[str, Any] | None:
    if not dependencies.actions.matches_transfer(event):
        return None
    dependencies.audit(
        event.thread_id,
        event.turn_id,
        "auto_guard_block",
        {
            "hook_event": "PreToolUse",
            "reason_code": "transfer_not_prepared_for_turn",
            "state_phase": state["phase"] if state else "missing",
        },
    )
    return dependencies.presentation.deny_tool(
        "Model Fit: для этого хода нет подготовленного переноса. Не повторяй прежние технические команды; обычные инструменты доступны после оценки текущего ввода."
    )


def authorize_transfer(
    event: ToolCheck,
    state: dict[str, Any],
    bound: dict[str, Any] | None,
    *,
    dependencies: Dependencies,
) -> dict[str, Any] | None:
    try:
        with dependencies.state.transaction(
            event.thread_id,
            nonblocking=True,
            operation="pre_tool_use",
            turn_id=event.turn_id,
        ) as slot:
            if slot.load() == state:
                Lifecycle.authorize_transfer(slot, state, dependencies.clock())
                if bound is not None:
                    dependencies.audit(
                        event.thread_id,
                        event.turn_id,
                        "auto_transfer_bound",
                        {"hook_event": "PreToolUse"},
                    )
                    return dependencies.presentation.allow_tool(bound)
                return None
        reason = "transfer_state_changed"
    except BlockingIOError:
        reason = "state_lock_busy"
    dependencies.audit(
        event.thread_id,
        event.turn_id,
        "auto_guard_block",
        {
            "hook_event": "PreToolUse",
            "reason_code": reason,
            "state_phase": state["phase"],
        },
    )
    return dependencies.presentation.deny_tool(
        "Model Fit: состояние переноса изменилось или занято; прежняя техническая команда не разрешена."
    )


def can_continue_failed_assessment(
    event: ToolCheck, state: dict[str, Any] | None, *, dependencies: Dependencies
) -> bool:
    pending = state.get("pending_assessment") if state else None
    return bool(
        state
        and isinstance(event.turn_id, str)
        and event.turn_id
        and state["phase"] in {"submitted", "passed", "ready"}
        and pending
        and pending.get("turn_id") == event.turn_id
        and pending.get("status") == "failed"
        and pending.get("failure_reason") == "assessment_failed"
        and not dependencies.actions.matches_transfer(event)
        and not dependencies.actions.matches_assessment(event)
    )


def guard_tool(
    event: ToolCheck, *, dependencies: Dependencies
) -> dict[str, Any] | None:
    thread_id = event.thread_id
    try:
        with dependencies.state.transaction(
            thread_id, nonblocking=True, operation="pre_tool_use", turn_id=event.turn_id
        ) as slot:
            state = slot.load()
    except BlockingIOError:
        state = dependencies.state.snapshot(thread_id)
        details = {
            "hook_event": "PreToolUse",
            "state_phase": state["phase"] if state else "missing",
        }
        details.update(dependencies.state.owner(thread_id))
        if can_continue_failed_assessment(event, state, dependencies=dependencies):
            dependencies.audit(
                thread_id,
                event.turn_id,
                "auto_guard_lock_contention",
                details | {"reason_code": "assessment_failed_continue"},
            )
            return None
        if (
            state is not None
            and not state.get("pending_assessment")
            and state["phase"] == "passed"
            and (state["source_turn_id"] == event.turn_id)
        ):
            dependencies.audit(
                thread_id,
                event.turn_id,
                "auto_guard_lock_contention",
                details | {"reason_code": "passed_same_turn"},
            )
            return guard_unprepared_transfer(event, state, dependencies=dependencies)
        if (
            state is not None
            and not state.get("pending_assessment")
            and state["phase"] == "queued"
            and isinstance(event.turn_id, str)
            and (state.get("replay_turn_id") == event.turn_id)
        ):
            dependencies.audit(
                thread_id,
                event.turn_id,
                "auto_guard_lock_contention",
                details | {"reason_code": "confirmed_replay_same_turn"},
            )
            return guard_replay_transfer(event, state, dependencies=dependencies)
        dependencies.audit(
            thread_id,
            event.turn_id,
            "auto_guard_block",
            details | {"reason_code": "state_lock_busy"},
        )
        return dependencies.presentation.deny_tool(
            "Model Fit: состояние переноса занято; технический ход не допускает новый инструмент."
        )
    pending = state.get("pending_assessment") if state is not None else None
    if pending is not None:
        if can_continue_failed_assessment(event, state, dependencies=dependencies):
            return None
        if pending[
            "turn_id"
        ] == event.turn_id and dependencies.actions.matches_assessment(event):
            return None
        if (
            state["phase"] in {"submitted", "passed"}
            and isinstance(event.turn_id, str)
            and pending["turn_id"] != event.turn_id
            and dependencies.actions.matches_assessment(event)
        ):
            try:
                with dependencies.native(dependencies.working_directory()) as app:
                    successor = app.unsubmitted_successor(
                        thread_id, pending["turn_id"], event.turn_id
                    )
                if successor is True:
                    with dependencies.state.transaction(
                        thread_id,
                        nonblocking=True,
                        operation="pre_tool_use",
                        turn_id=event.turn_id,
                    ) as slot:
                        if (
                            slot.load() == state
                            and load_blocking_recommendation(
                                thread_id, dependencies=dependencies
                            )
                            is None
                        ):
                            Lifecycle.admit(
                                slot,
                                event.turn_id,
                                "unknown",
                                state.get("profile_context_turn_id"),
                                supersede_assessment=True,
                            )
                            dependencies.audit(
                                thread_id,
                                event.turn_id,
                                "auto_unknown",
                                {
                                    "hook_event": "PreToolUse",
                                    "reason_code": "native_turn_without_submission",
                                    "state_phase": state["phase"],
                                },
                            )
                            return None
            except (OSError, ValueError, RuntimeError):
                pass
        dependencies.audit(
            thread_id,
            event.turn_id,
            "auto_guard_block",
            {
                "hook_event": "PreToolUse",
                "reason_code": "assessment_pending",
                "state_phase": state["phase"],
            },
        )
        return dependencies.presentation.deny_tool(
            "Model Fit: сначала выполни техническую команду оценки принятого ввода. Исходная задача ещё не проверена."
        )
    if (
        state is not None
        and state["phase"] == "ready"
        and event.turn_id in {state["source_turn_id"], state.get("control_turn_id")}
        and dependencies.actions.matches_assessment(event)
    ):
        return None
    replay_denial = guard_replay_transfer(event, state, dependencies=dependencies)
    if replay_denial is not None:
        return replay_denial
    if (
        state is None
        or state["phase"] == "passed"
        or event.turn_id not in {state["source_turn_id"], state.get("control_turn_id")}
    ):
        return guard_unprepared_transfer(event, state, dependencies=dependencies)
    if state["phase"] == "ready" and (
        dependencies.actions.matches_profile_switch(event, state)
        or dependencies.actions.matches_queue(event, state)
    ):
        return authorize_transfer(event, state, None, dependencies=dependencies)
    if state["phase"] == "ready":
        bound = dependencies.actions.bound_transfer_input(event, state)
        if bound is not None:
            return authorize_transfer(event, state, bound, dependencies=dependencies)
    dependencies.audit(
        thread_id,
        event.turn_id,
        "auto_guard_block",
        {
            "hook_event": "PreToolUse",
            "reason_code": "technical_turn_tool_denied",
            "state_phase": state["phase"],
        },
    )
    return dependencies.presentation.deny_tool(
        "Model Fit: технический ход допускает только смену профиля и постановку исходного запроса в очередь."
    )


def guard_replay_answer(
    event: AnswerCheck, *, dependencies: Dependencies
) -> dict[str, Any] | None:
    if event.stop_hook_active is True:
        return None
    thread_id = event.thread_id
    turn_id = event.turn_id
    answer = event.answer
    if (
        not isinstance(turn_id, str)
        or not isinstance(answer, str)
        or (not answer.strip())
    ):
        return None
    with dependencies.state.transaction(
        thread_id, operation="stop", turn_id=turn_id
    ) as slot:
        state = slot.load()
        pending = state.get("pending_assessment") if state is not None else None
        if pending is not None:
            if pending["turn_id"] != turn_id or pending["status"] == "failed":
                return None
            return dependencies.presentation.block(
                "Model Fit: перед ответом выполни техническую команду оценки из инструкции текущего хода."
            )
        if (
            state is not None
            and state["phase"] == "ready"
            and (turn_id in {state["source_turn_id"], state.get("control_turn_id")})
        ):
            Lifecycle.admit(slot, turn_id)
            dependencies.audit(
                thread_id,
                turn_id,
                "auto_handoff_not_queued",
                {
                    "hook_event": "Stop",
                    "reason_code": "technical_turn_finished_before_queue",
                    "state_phase": "ready",
                },
            )
            return None
    if state is None:
        return None
    assessed = (
        state["phase"] == "passed"
        and state["source_turn_id"] == turn_id
        and state.get("assessment_decision") == "keep"
    )
    replay_bound = state["phase"] == "queued" and state.get("replay_turn_id") == turn_id
    if not assessed and not replay_bound:
        return None
    with dependencies.native(event.working_directory) as app:
        if assessed:
            content = app.accepted_input(thread_id, turn_id).content
            verified_input = content
        else:
            content = app.handoff_input(thread_id, state)
            replay = app.replay_input(thread_id, turn_id)
            if replay is None:
                dependencies.audit(
                    thread_id, turn_id, "auto_stop_steered_or_unverified"
                )
                return None
            verified_input = replay
            if dependencies.input.input_digest(replay) != state["queued_input_digest"]:
                dependencies.audit(thread_id, turn_id, "auto_stop_input_unverified")
                return None
    if any((item.get("type") != "text" for item in content)):
        dependencies.audit(thread_id, turn_id, "auto_stop_multimodal_unchecked")
        return None
    request = dependencies.input.input_text(content).strip()
    if (
        not request
        or len(request) > MAX_REPLAY_EVAL_CHARS
        or len(answer) > MAX_REPLAY_EVAL_CHARS
    ):
        dependencies.audit(thread_id, turn_id, "auto_stop_size_unchecked")
        return None
    verdict = dependencies.relevance(request, state.get("task_inference", ""), answer)
    dependencies.audit(thread_id, turn_id, f"auto_stop_{verdict}")
    if verdict != "unrelated":
        return None
    with dependencies.state.transaction(
        thread_id, operation="stop", turn_id=turn_id
    ) as slot:
        current = slot.load()
    if current != state:
        return None
    with dependencies.native(event.working_directory) as app:
        latest_input = (
            app.accepted_input(thread_id, turn_id).content
            if assessed
            else app.replay_input(thread_id, turn_id)
        )
    if latest_input is None or dependencies.input.input_digest(
        latest_input
    ) != dependencies.input.input_digest(verified_input):
        dependencies.audit(thread_id, turn_id, "auto_stop_input_changed")
        return None
    with dependencies.state.transaction(
        thread_id, operation="stop", turn_id=turn_id
    ) as slot:
        current = slot.load()
    if current != state:
        return None
    return dependencies.presentation.block(dependencies.presentation.replay_stop_reason)
