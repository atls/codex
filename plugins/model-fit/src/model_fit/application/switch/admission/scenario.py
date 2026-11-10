from __future__ import annotations

from model_fit.application.submission.types.json import JsonValue

from model_fit.application.switch.admission.types.result import (
    AllowedTool,
    DeniedTool,
    ToolAdmission,
)

from typing import Callable

from model_fit.application.switch.admission.types.tools import TransferTools
from model_fit.application.switch.types.audit import AuditWriter
from model_fit.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.application.assessment.types.cache import (
    ResultCache,
)
from model_fit.application.switch.state.types.storage import TransferStateStore
from model_fit.application.switch.admission.types.input import ToolAdmissionInput
from model_fit.application.switch.admission.guards.continuation import (
    can_continue_failed_assessment,
)
from model_fit.application.switch.admission.denial import (
    deny_replay_transfer,
    deny_unprepared_transfer,
)
from model_fit.application.switch.admission.authorization import authorize_transfer
from model_fit.application.handoff.types.clock import Clock
from model_fit.application.switch.admission.recovery import (
    recover_unsubmitted_successor,
)


def guard_tool(
    event: ToolAdmissionInput,
    *,
    actions: TransferTools,
    audit: AuditWriter,
    recommendations: ResultCache,
    clock: Clock,
    conversation: NativeConversationFactory,
    store: TransferStateStore,
    working_directory: Callable[[], str],
    replay_context: str,
) -> ToolAdmission:
    thread_id = event.thread_id
    try:
        with store.transaction(
            thread_id, nonblocking=True, operation="pre_tool_use", turn_id=event.turn_id
        ) as slot:
            state = slot.load()
    except BlockingIOError:
        state = store.snapshot(thread_id)
        details: dict[str, JsonValue] = {
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
            return AllowedTool()
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
            return deny_unprepared_transfer(
                event,
                state,
                actions=actions,
                audit=audit,
                replay_context=replay_context,
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
            return deny_replay_transfer(
                event,
                state,
                actions=actions,
                audit=audit,
                replay_context=replay_context,
            )
        audit(
            thread_id,
            event.turn_id,
            "auto_guard_block",
            details | {"reason_code": "state_lock_busy"},
        )
        return DeniedTool(
            "Model Fit: handoff state is busy; the technical turn cannot admit a new tool."
        )
    pending = state.get("pending_assessment") if state is not None else None
    if state is not None and pending is not None:
        if can_continue_failed_assessment(event, state, actions=actions):
            return AllowedTool()
        if pending["turn_id"] == event.turn_id and actions.matches_assessment(event):
            return AllowedTool()
        if (
            state["phase"] in {"submitted", "passed"}
            and isinstance(event.turn_id, str)
            and (pending["turn_id"] != event.turn_id)
            and actions.matches_assessment(event)
        ):
            if recover_unsubmitted_successor(
                event,
                state,
                conversation=conversation,
                working_directory=working_directory,
                store=store,
                recommendations=recommendations,
                audit=audit,
            ):
                return AllowedTool()
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
        return DeniedTool(
            "Model Fit: first run the technical assessment command for the accepted input. The original task has not yet been assessed."
        )
    if (
        state is not None
        and state["phase"] == "ready"
        and (event.turn_id in {state["source_turn_id"], state.get("control_turn_id")})
        and actions.matches_assessment(event)
    ):
        return AllowedTool()
    replay_denial = deny_replay_transfer(
        event, state, actions=actions, audit=audit, replay_context=replay_context
    )
    if isinstance(replay_denial, DeniedTool):
        return replay_denial
    if (
        state is None
        or state["phase"] == "passed"
        or event.turn_id not in {state["source_turn_id"], state.get("control_turn_id")}
    ):
        return deny_unprepared_transfer(
            event, state, actions=actions, audit=audit, replay_context=replay_context
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
    return DeniedTool(
        "Model Fit: this technical turn permits only a profile change and queueing the original request."
    )
