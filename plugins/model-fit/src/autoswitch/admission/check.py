from __future__ import annotations

from typing import Any, Callable

from model_fit.autoswitch.state import transitions
from model_fit.autoswitch.admission.types.tools import TransferTools
from model_fit.autoswitch.types.audit import AuditWriter
from model_fit.autoswitch.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.autoswitch.types.output import HookOutputRenderer
from model_fit.autoswitch.recommendation.types.storage import (
    RecommendationStore,
)
from model_fit.autoswitch.state.types.storage import TransferStateStore
from model_fit.autoswitch.admission.types.input import ToolAdmissionInput
from model_fit.autoswitch.recommendation.check import load_blocking_recommendation
from model_fit.autoswitch.admission.continuation import (
    can_continue_failed_assessment,
    guard_replay_transfer,
)
from model_fit.autoswitch.admission.authorization import authorize_transfer
from model_fit.autoswitch.handoff.types.clock import Clock


def guard_unprepared_transfer(
    event: ToolAdmissionInput,
    state: dict[str, Any] | None,
    *,
    actions: TransferTools,
    audit: AuditWriter,
    presentation: HookOutputRenderer,
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
        "Model Fit: no handoff is prepared for this turn. Do not repeat previous technical commands; ordinary tools are available after assessment of the current input."
    )


def guard_tool(
    event: ToolAdmissionInput,
    *,
    actions: TransferTools,
    audit: AuditWriter,
    recommendations: RecommendationStore,
    clock: Clock,
    conversation: NativeConversationFactory,
    presentation: HookOutputRenderer,
    store: TransferStateStore,
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
            "Model Fit: handoff state is busy; the technical turn cannot admit a new tool."
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
            "Model Fit: first run the technical assessment command for the accepted input. The original task has not yet been assessed."
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
        "Model Fit: this technical turn permits only a profile change and queueing the original request."
    )
