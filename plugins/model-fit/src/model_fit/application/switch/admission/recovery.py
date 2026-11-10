from model_fit.application.switch.lifecycle import (
    profile_choice as profile_choice_lifecycle,
)
from collections.abc import Callable
from model_fit.application.switch.admission.types.input import ToolAdmissionInput
from model_fit.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from model_fit.application.switch.recommendation.types.storage import (
    RecommendationStore,
)
from model_fit.application.switch.recommendation.check import (
    load_blocking_recommendation,
)
from model_fit.application.switch.state.types.record import HandoffStateRecord
from model_fit.application.switch.state.types.storage import TransferStateStore
from model_fit.application.switch.types.audit import AuditWriter


def recover_unsubmitted_successor(
    event: ToolAdmissionInput,
    state: HandoffStateRecord,
    *,
    conversation: NativeConversationFactory,
    working_directory: Callable[[], str],
    store: TransferStateStore,
    recommendations: RecommendationStore,
    audit: AuditWriter,
) -> bool:
    turn_id = event.turn_id
    if not isinstance(turn_id, str):
        return False
    pending = state["pending_assessment"]
    if pending is None:
        return False
    try:
        with conversation(working_directory()) as app:
            successor = app.unsubmitted_successor(
                event.thread_id, pending["turn_id"], turn_id
            )
        if successor is True:
            with store.transaction(
                event.thread_id,
                nonblocking=True,
                operation="pre_tool_use",
                turn_id=event.turn_id,
            ) as slot:
                if (
                    slot.load() == state
                    and load_blocking_recommendation(
                        event.thread_id,
                        recommendations=recommendations,
                    )
                    is None
                ):
                    profile_choice_lifecycle.admit(
                        slot,
                        turn_id,
                        "unknown",
                        state.get("profile_context_turn_id"),
                        supersede_assessment=True,
                    )
                    audit(
                        event.thread_id,
                        event.turn_id,
                        "auto_unknown",
                        {
                            "hook_event": "PreToolUse",
                            "reason_code": "native_turn_without_submission",
                            "state_phase": state["phase"],
                        },
                    )
                    return True
    except (OSError, ValueError, RuntimeError):
        pass
    return False
