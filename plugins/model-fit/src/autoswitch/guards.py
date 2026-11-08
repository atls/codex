from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Callable

from model_fit.autoswitch import transitions
from model_fit.autoswitch.ports.actions import Actions
from model_fit.autoswitch.ports.conversation import Conversation
from model_fit.autoswitch.ports.presentation import Presentation
from model_fit.autoswitch.ports.recommendations import Recommendations
from model_fit.autoswitch.ports.store import Store
from model_fit.autoswitch.recommendation import load_blocking_recommendation
from model_fit.autoswitch.replay import (
    can_continue_failed_assessment,
    guard_replay_transfer,
)
from model_fit.autoswitch.requests.tool_check import ToolCheck


def guard_unprepared_transfer(
    event: ToolCheck,
    state: dict[str, Any] | None,
    *,
    actions: Actions,
    audit: Callable[..., Any],
    presentation: Presentation,
) -> dict[str, Any] | None:
    if not actions.matches_transfer(event):
        return None
    audit(
        event.thread_id,
        event.turn_id,
        "auto_guard_block",
        {
            "hook_event": "PreToolUse",
            "reason_code": "transfer_not_prepared_for_turn",
            "state_phase": state["phase"] if state else "missing",
        },
    )
    return presentation.deny_tool(
        "Model Fit: для этого хода нет подготовленного переноса. Не повторяй прежние технические команды; обычные инструменты доступны после оценки текущего ввода."
    )


def authorize_transfer(
    event: ToolCheck,
    state: dict[str, Any],
    bound: dict[str, Any] | None,
    *,
    audit: Callable[..., Any],
    clock: Callable[[], float],
    presentation: Presentation,
    store: Store,
) -> dict[str, Any] | None:
    try:
        with store.transaction(
            event.thread_id,
            nonblocking=True,
            operation="pre_tool_use",
            turn_id=event.turn_id,
        ) as slot:
            if slot.load() == state:
                transitions.authorize_transfer(slot, state, clock())
                if bound is not None:
                    audit(
                        event.thread_id,
                        event.turn_id,
                        "auto_transfer_bound",
                        {"hook_event": "PreToolUse"},
                    )
                    return presentation.allow_tool(bound)
                return None
        reason = "transfer_state_changed"
    except BlockingIOError:
        reason = "state_lock_busy"
    audit(
        event.thread_id,
        event.turn_id,
        "auto_guard_block",
        {
            "hook_event": "PreToolUse",
            "reason_code": reason,
            "state_phase": state["phase"],
        },
    )
    return presentation.deny_tool(
        "Model Fit: состояние переноса изменилось или занято; прежняя техническая команда не разрешена."
    )


def guard_tool(
    event: ToolCheck,
    *,
    actions: Actions,
    audit: Callable[..., Any],
    recommendations: Recommendations,
    clock: Callable[[], float],
    conversation: Callable[[object], AbstractContextManager[Conversation]],
    presentation: Presentation,
    store: Store,
    working_directory: Callable[[], str],
) -> dict[str, Any] | None:
    thread_id = event.thread_id
    try:
        with store.transaction(
            thread_id, nonblocking=True, operation="pre_tool_use", turn_id=event.turn_id
        ) as slot:
            state = slot.load()
    except BlockingIOError:
        state = store.snapshot(thread_id)
        details = {
            "hook_event": "PreToolUse",
            "state_phase": state["phase"] if state else "missing",
        }
        details.update(store.owner(thread_id))
        if can_continue_failed_assessment(event, state, actions=actions):
            audit(
                thread_id,
                event.turn_id,
                "auto_guard_lock_contention",
                details | {"reason_code": "assessment_failed_continue"},
            )
            return None
        if (
            state is not None
            and (not state.get("pending_assessment"))
            and (state["phase"] == "passed")
            and (state["source_turn_id"] == event.turn_id)
        ):
            audit(
                thread_id,
                event.turn_id,
                "auto_guard_lock_contention",
                details | {"reason_code": "passed_same_turn"},
            )
            return guard_unprepared_transfer(
                event, state, actions=actions, audit=audit, presentation=presentation
            )
        if (
            state is not None
            and (not state.get("pending_assessment"))
            and (state["phase"] == "queued")
            and isinstance(event.turn_id, str)
            and (state.get("replay_turn_id") == event.turn_id)
        ):
            audit(
                thread_id,
                event.turn_id,
                "auto_guard_lock_contention",
                details | {"reason_code": "confirmed_replay_same_turn"},
            )
            return guard_replay_transfer(
                event, state, actions=actions, audit=audit, presentation=presentation
            )
        audit(
            thread_id,
            event.turn_id,
            "auto_guard_block",
            details | {"reason_code": "state_lock_busy"},
        )
        return presentation.deny_tool(
            "Model Fit: состояние переноса занято; технический ход не допускает новый инструмент."
        )
    pending = state.get("pending_assessment") if state is not None else None
    if pending is not None:
        if can_continue_failed_assessment(event, state, actions=actions):
            return None
        if pending["turn_id"] == event.turn_id and actions.matches_assessment(event):
            return None
        if (
            state["phase"] in {"submitted", "passed"}
            and isinstance(event.turn_id, str)
            and (pending["turn_id"] != event.turn_id)
            and actions.matches_assessment(event)
        ):
            try:
                with conversation(working_directory()) as app:
                    successor = app.unsubmitted_successor(
                        thread_id, pending["turn_id"], event.turn_id
                    )
                if successor is True:
                    with store.transaction(
                        thread_id,
                        nonblocking=True,
                        operation="pre_tool_use",
                        turn_id=event.turn_id,
                    ) as slot:
                        if (
                            slot.load() == state
                            and load_blocking_recommendation(
                                thread_id,
                                recommendations=recommendations,
                                presentation=presentation,
                            )
                            is None
                        ):
                            transitions.admit(
                                slot,
                                event.turn_id,
                                "unknown",
                                state.get("profile_context_turn_id"),
                                supersede_assessment=True,
                            )
                            audit(
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
        audit(
            thread_id,
            event.turn_id,
            "auto_guard_block",
            {
                "hook_event": "PreToolUse",
                "reason_code": "assessment_pending",
                "state_phase": state["phase"],
            },
        )
        return presentation.deny_tool(
            "Model Fit: сначала выполни техническую команду оценки принятого ввода. Исходная задача ещё не проверена."
        )
    if (
        state is not None
        and state["phase"] == "ready"
        and (event.turn_id in {state["source_turn_id"], state.get("control_turn_id")})
        and actions.matches_assessment(event)
    ):
        return None
    replay_denial = guard_replay_transfer(
        event, state, actions=actions, audit=audit, presentation=presentation
    )
    if replay_denial is not None:
        return replay_denial
    if (
        state is None
        or state["phase"] == "passed"
        or event.turn_id not in {state["source_turn_id"], state.get("control_turn_id")}
    ):
        return guard_unprepared_transfer(
            event, state, actions=actions, audit=audit, presentation=presentation
        )
    if state["phase"] == "ready" and (
        actions.matches_profile_switch(event, state)
        or actions.matches_queue(event, state)
    ):
        return authorize_transfer(
            event,
            state,
            None,
            audit=audit,
            clock=clock,
            presentation=presentation,
            store=store,
        )
    if state["phase"] == "ready":
        bound = actions.bound_transfer_input(event, state)
        if bound is not None:
            return authorize_transfer(
                event,
                state,
                bound,
                audit=audit,
                clock=clock,
                presentation=presentation,
                store=store,
            )
    audit(
        thread_id,
        event.turn_id,
        "auto_guard_block",
        {
            "hook_event": "PreToolUse",
            "reason_code": "technical_turn_tool_denied",
            "state_phase": state["phase"],
        },
    )
    return presentation.deny_tool(
        "Model Fit: технический ход допускает только смену профиля и постановку исходного запроса в очередь."
    )
