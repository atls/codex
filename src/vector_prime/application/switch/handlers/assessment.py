from __future__ import annotations

from vector_prime.application.handoff.types.state import QueuedTransfer
from vector_prime.application.switch.helpers.transfer import transfer_instruction
from vector_prime.application.switch.admission.recovery import admit_assessment_recovery

from vector_prime.application.assessment.exceptions.context_unavailable import (
    ContextUnavailable,
)

from vector_prime.application.handoff.types.replay import (
    ReplayBound,
    OwnerProfileChanged,
)
from vector_prime.application.handoff import lifecycle as handoff_lifecycle
from vector_prime.application.switch import lifecycle as switch_lifecycle


from collections.abc import Callable

from vector_prime.application.assessment.guards.generation import require_generation
from vector_prime.application.assessment.types.profile import ActiveProfile
from vector_prime.application.assessment.types.state import PendingAssessment, Running
from vector_prime.application.assessment.exceptions.superseded import (
    AssessmentSuperseded,
)
from vector_prime.application.switch.exceptions.unavailable import SubmissionUnavailable
from vector_prime.application.switch.handlers.processing import evaluate
from vector_prime.application.assessment.types.execution import AssessmentRunner
from vector_prime.application.switch.types.audit import AuditWriter
from vector_prime.application.assessment.types.execution import AssessmentContextReader
from vector_prime.application.handoff.types.conversation import (
    NativeConversationFactory,
)
from vector_prime.application.submission.helpers import content as codec
from vector_prime.application.switch.types.disposition import ContinueWork
from vector_prime.application.switch.types.disposition import PreparedTransfer
from vector_prime.application.switch.types.disposition import QueuePending
from vector_prime.application.switch.types.disposition import TurnDisposition
from vector_prime.application.switch.types.disposition import TurnNotice
from vector_prime.application.assessment.types.result import UnknownAssessment
from vector_prime.application.switch.types.disposition import WorkContext
from vector_prime.application.switch.disposition import (
    assessment_audit_outcome,
    blocks_work,
)

from vector_prime.application.submission.types.input import SubmissionInput
from vector_prime.application.assessment.types.cache import (
    ResultCache,
)
from vector_prime.application.switch.types.storage import TransferStateStore
from vector_prime.application.switch.admission.recommendation import (
    blocking_recommendation,
)
from vector_prime.application.handoff.types.clock import Clock


def assess(
    decode: Callable[[PendingAssessment, str], SubmissionInput],
    *,
    assessor: AssessmentRunner,
    audit: AuditWriter,
    recommendations: ResultCache,
    caller_thread: str | None,
    clock: Clock,
    conversation: NativeConversationFactory,
    read_context: AssessmentContextReader,
    store: TransferStateStore,
) -> TurnDisposition:
    try:
        thread_id = caller_thread
        if not thread_id:
            raise SubmissionUnavailable(None, "native_thread_required")
        with store.transaction(thread_id, operation="assessment") as slot:
            state = slot.load()
            if state is None:
                raise SubmissionUnavailable(thread_id, "submission_missing")
            pending = state.get("pending_assessment")
            if pending is None:
                if state["phase"] == "ready":
                    return PreparedTransfer(
                        thread_id, state["source_turn_id"], transfer_instruction(state)
                    )
                if state["phase"] == "queued":
                    transfer = state.get("transfer")
                    if (
                        isinstance(transfer, QueuedTransfer)
                        and transfer.replay_turn_id is not None
                    ):
                        return ContinueWork(WorkContext.REPLAY)
                    return QueuePending()
                if state.get("assessment_decision") == "keep":
                    return ContinueWork(WorkContext.ASSESSED)
                return TurnNotice(
                    "Model Fit: no new assessment was performed; suitability is unknown."
                )
            if isinstance(pending.progress, Running):
                return TurnNotice(
                    "Model Fit: assessment is already running; wait for the first invocation's result."
                )
            pending = switch_lifecycle.start_assessment(slot)
        event = decode(pending, "")
        if event.thread_id != thread_id:
            raise ValueError("Submitted input belongs to another Codex thread")
        try:
            try:
                request = read_context(event)
            except ContextUnavailable as error:
                capability = error.reason_code
                if (
                    capability is None
                    or state["phase"] not in {"submitted", "passed"}
                    or state.get("profile_context_turn_id") is not None
                ):
                    raise
                with store.transaction(
                    thread_id,
                    nonblocking=True,
                    operation="assessment",
                    turn_id=event.turn_id,
                ) as slot:
                    current = slot.load()
                    switch_lifecycle.require_submission(slot, pending)
                    if pending.prompt_hash is None or pending.empty_text is None:
                        raise ValueError("Pending assessment has no input evidence")
                    blocked = blocking_recommendation(
                        event,
                        prompt_hash=pending.prompt_hash,
                        empty_input=pending.empty_text,
                        recommendations=recommendations,
                    )
                    if blocked is not None:
                        recommendations.clear(thread_id)
                    switch_lifecycle.admit(slot, event.turn_id, "unknown")
                    switch_lifecycle.finish_assessment(slot, pending)
                audit(
                    thread_id,
                    event.turn_id,
                    "auto_session_unavailable",
                    {"hook_event": "assessment", "reason_code": capability},
                )
                audit(
                    thread_id,
                    event.turn_id,
                    "auto_unknown",
                    {"hook_event": "assessment"},
                )
                return UnknownAssessment(
                    "Native chat context is unavailable for assessment."
                )
            else:
                with conversation(event.working_directory) as app:
                    accepted = app.accepted_input(thread_id, event.turn_id)
                    queued = (
                        app.queued_ids(thread_id)
                        if state["phase"] == "queued"
                        else set()
                    )
                event = decode(pending, codec.hook_prompt(accepted.source_content))
                request = {
                    **request,
                    "task": codec.hook_prompt(accepted.content) or request["task"],
                }
                if (
                    state["phase"] == "passed"
                    and state.get("assessed_profile") is not None
                    and (state["assessed_profile"] != request["active_profile"])
                ):
                    with store.transaction(
                        thread_id, operation="assessment", turn_id=event.turn_id
                    ) as slot:
                        switch_lifecycle.require_submission(slot, pending)
                        switch_lifecycle.admit(
                            slot,
                            event.turn_id,
                            "native_override",
                            event.turn_id,
                            native_profile=request["active_profile"],
                        )
                    audit(
                        thread_id,
                        event.turn_id,
                        "auto_native_profile_override",
                        {
                            "hook_event": "assessment",
                            "reason_code": "native_choice_after_keep",
                        },
                    )
                if state["phase"] == "queued":
                    with store.transaction(
                        thread_id, operation="assessment", turn_id=event.turn_id
                    ) as slot:
                        switch_lifecycle.require_submission(slot, pending)
                        replay = handoff_lifecycle.reconcile_accepted(
                            slot,
                            turn_id=event.turn_id,
                            accepted=accepted,
                            profile=request["active_profile"],
                            queued_ids=queued,
                        )
                        if isinstance(replay, ReplayBound):
                            audit(thread_id, event.turn_id, "auto_replay")
                            return ContinueWork(WorkContext.REPLAY)
                        if isinstance(replay, OwnerProfileChanged):
                            switch_lifecycle.admit(
                                slot,
                                event.turn_id,
                                "native_override",
                                event.turn_id,
                                native_profile=request["active_profile"],
                            )
                            if replay.same_source:
                                switch_lifecycle.finish_assessment(slot, pending)
                                audit(
                                    thread_id,
                                    event.turn_id,
                                    "auto_native_profile_override",
                                )
                                return ContinueWork(
                                    "Model Fit: the native owner changed the profile after queueing. The current profile is retained; its suitability was not reassessed here. Perform the current original request with all current attachments and annotations."
                                )
                            audit(
                                thread_id,
                                event.turn_id,
                                "auto_native_profile_override",
                                {
                                    "hook_event": "assessment",
                                    "reason_code": "native_choice_before_new_message",
                                },
                            )
                    audit(
                        thread_id,
                        event.turn_id,
                        "auto_native_input_changed"
                        if replay.same_source
                        else "auto_native_queue_detached",
                    )
                request = {**request, "input": accepted.content}
                output = evaluate(
                    event,
                    expected_submission=pending,
                    assessor=assessor,
                    audit=audit,
                    recommendations=recommendations,
                    clock=clock,
                    conversation=conversation,
                    read_context=lambda _: request,
                    store=store,
                )
                with conversation(event.working_directory) as app:
                    current_model, current_effort = app.profile(thread_id)
                if not isinstance(current_model, str) or not isinstance(
                    current_effort, str
                ):
                    raise ValueError("Native profile unavailable after assessment")
                if (current_model, current_effort) != (
                    request["active_profile"]["model"],
                    request["active_profile"]["effort"],
                ):
                    selected: ActiveProfile = {
                        **request["active_profile"],
                        "model": current_model,
                        "effort": current_effort,
                    }
                    with store.transaction(
                        thread_id, operation="assessment", turn_id=event.turn_id
                    ) as slot:
                        current = slot.load()
                        require_generation(
                            thread_id,
                            event.turn_id,
                            pending.generation,
                            current.get("assessment_generation")
                            if current is not None
                            else None,
                        )
                        assert current is not None
                        if current["phase"] not in {"ready", "passed", "submitted"}:
                            raise RuntimeError(
                                "Native choice cannot discard unresolved transfer"
                            )
                        cached = recommendations.load(thread_id)
                        if (
                            cached is not None
                            and cached["active_profile"] == request["active_profile"]
                            and (
                                cached["prompt_hash"] == codec.prompt_digest(event.text)
                            )
                        ):
                            recommendations.clear(thread_id)
                        switch_lifecycle.admit(
                            slot,
                            event.turn_id,
                            "native_override",
                            event.turn_id,
                            native_profile=selected,
                        )
                        switch_lifecycle.finish_assessment(
                            slot, pending, assessed_profile=selected
                        )
                    audit(
                        thread_id,
                        event.turn_id,
                        "auto_native_profile_override",
                        {
                            "hook_event": "assessment",
                            "reason_code": "native_choice_during_assessment",
                        },
                    )
                    return ContinueWork(
                        "Model Fit: the native owner changed the profile during assessment. The previous recommendation is cancelled; the current choice is retained and its suitability is unknown. Perform the original request with its current attachments."
                    )
            with store.transaction(
                thread_id, operation="assessment", turn_id=event.turn_id
            ) as slot:
                current = slot.load()
                require_generation(
                    thread_id,
                    event.turn_id,
                    pending.generation,
                    current.get("assessment_generation")
                    if current is not None
                    else None,
                )
                if output is not None and blocks_work(output):
                    switch_lifecycle.fail_assessment(slot, pending)
                else:
                    switch_lifecycle.finish_assessment(
                        slot, pending, assessed_profile=request["active_profile"]
                    )
            audit(
                thread_id,
                event.turn_id,
                assessment_audit_outcome(output),
                {
                    "hook_event": "assessment",
                    "assessment_generation": str(pending.generation),
                    "root_session_id": event.session_id or thread_id,
                },
            )
            return output if output is not None else ContinueWork(WorkContext.ASSESSED)
        except AssessmentSuperseded:
            raise
        except Exception as error:
            recovered = admit_assessment_recovery(
                event, pending, error, store=store, audit=audit
            )
            if recovered is not None:
                return recovered
            try:
                with store.transaction(
                    thread_id,
                    nonblocking=True,
                    operation="assessment",
                    turn_id=event.turn_id,
                ) as slot:
                    switch_lifecycle.fail_assessment(
                        slot, pending, reason="assessment_failed"
                    )
            except BlockingIOError:
                pass
            raise
    except AssessmentSuperseded as error:
        audit(
            error.thread_id,
            error.turn_id,
            "auto_assessment_superseded",
            {
                "hook_event": "assessment",
                "reason_code": "newer_submission",
                "assessment_generation": error.generation,
            },
        )
        return ContinueWork(
            "The previous Model Fit assessment was superseded and not applied. Use the instruction for the latest accepted input; do not repeat a handoff based on the cancelled assessment."
        )
