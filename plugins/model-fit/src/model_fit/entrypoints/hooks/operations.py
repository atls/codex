from model_fit.application.answer.types.result import AnswerVerdict
import model_fit.application.answer.relevance as answer_check
from model_fit.entrypoints.hooks.types.output import HookOutput
from model_fit.application.switch.admission.types.result import DeniedTool
from collections.abc import Callable
from model_fit.application.submission.types.json import JsonValue
from model_fit.application.assessment.types.request import ProfileAssessmentInput
from model_fit.application.assessment.types.execution import AssessmentRunner
from model_fit.application.handoff.types.conversation import (
    NativeConversationFactory,
)
import os
import time
from model_fit.entrypoints.hooks.delivery import deliver_disposition

import model_fit.infrastructure.adapters.codex.answer as answer_relevance
from model_fit.application.switch.handlers.completion import (
    finish as run_guard_replay_answer,
)
from model_fit.application.handoff.lifecycle import enqueue as run_enqueue
from model_fit.application.switch.admission.handler import guard_tool as run_guard_tool
from model_fit.application.switch.admission.guards.continuation import (
    can_continue_admitted_tool as continue_tool,
)
from model_fit.entrypoints.hooks.tool_action import NativeTransferTools
from model_fit.entrypoints.hooks.input import (
    answer_input,
    prompt_input,
    submitted_prompt,
    tool_input,
)
from model_fit.entrypoints.hooks.presentation import (
    HookPresentation,
)
from model_fit.infrastructure.adapters.codex.assessment import triage
from model_fit.infrastructure.adapters.codex.context import assessment_context
from model_fit.infrastructure.adapters.codex.conversation import ConversationGateway
from model_fit.infrastructure.adapters.codex.transport.reader import AppServerReader
from model_fit.infrastructure.adapters.codex.history import (
    queued_ids,
    session_input,
)
from model_fit.infrastructure.adapters.filesystem.audit import record_audit
from model_fit.infrastructure.adapters.filesystem.assessment_cache import (
    FileAssessmentCache,
)
from model_fit.infrastructure.adapters.filesystem.store import FileStore
from model_fit.application.switch.handlers.submission import accept as run_submit
from model_fit.application.switch.handlers.assessment import (
    assess as run_assess_submitted,
)
from model_fit.application.switch.handlers.reassessment import reassess as run_reassess


def native_conversation(
    native_factory: Callable[[str], AppServerReader] | None = None,
) -> NativeConversationFactory:

    def open_conversation(cwd: str | None) -> ConversationGateway:
        if cwd is None:
            raise KeyError("cwd")
        if not isinstance(cwd, str):
            raise ValueError("Native working directory is unavailable")
        return ConversationGateway(
            (native_factory or AppServerReader)(cwd), queue_reader=queued_ids
        )

    return open_conversation


def enqueue_handoff(
    thread_id: str,
    turn_id: str,
    *,
    native_factory: Callable[[str], AppServerReader] | None = None,
) -> dict[str, str]:
    result = run_enqueue(
        thread_id,
        turn_id,
        caller_thread=os.environ.get("CODEX_THREAD_ID"),
        clock=time.time,
        conversation=native_conversation(native_factory),
        store=FileStore(),
        working_directory=os.getcwd,
    )
    return {
        "queued_submission_id": result.submission_id,
        "status": "already_queued" if result.already_confirmed else "queued",
    }


def guard_tool(event: dict[str, JsonValue]) -> HookOutput | None:
    result = run_guard_tool(
        tool_input(event),
        actions=NativeTransferTools(),
        audit=record_audit,
        recommendations=FileAssessmentCache(),
        clock=time.time,
        conversation=native_conversation(None),
        replay_context=HookPresentation.replay_context,
        store=FileStore(),
        working_directory=os.getcwd,
    )

    if isinstance(result, DeniedTool):
        return HookPresentation().deny_tool(result.reason)
    if result.updated_input is not None:
        return HookPresentation().allow_tool(result.updated_input)
    return None


def guard_replay_answer(
    event: dict[str, JsonValue],
    *,
    native_factory: Callable[[str], AppServerReader] | None = None,
) -> HookOutput | None:
    result = run_guard_replay_answer(
        answer_input(event),
        audit=record_audit,
        conversation=native_conversation(native_factory),
        relevance=check_answer,
        store=FileStore(),
    )
    return deliver_disposition(result, store=FileStore(), audit=record_audit)


def submit_prompt(
    event: dict[str, JsonValue],
    *,
    context_reader: Callable[[object], ProfileAssessmentInput] | None = None,
    assessor: AssessmentRunner | None = None,
    native_factory: Callable[[str], AppServerReader] | None = None,
) -> HookOutput | None:
    result = run_submit(
        prompt_input(event),
        assessor=assessor or triage,
        audit=record_audit,
        recommendations=FileAssessmentCache(),
        clock=time.time,
        conversation=native_conversation(native_factory),
        read_context=lambda request: assessment_context(
            request.source, reader=context_reader or session_input
        ),
        store=FileStore(),
    )
    return deliver_disposition(result, store=FileStore(), audit=record_audit)


def assess_submitted(
    *,
    context_reader: Callable[[object], ProfileAssessmentInput] | None = None,
    assessor: AssessmentRunner | None = None,
    native_factory: Callable[[str], AppServerReader] | None = None,
) -> HookOutput:
    result = run_assess_submitted(
        submitted_prompt,
        assessor=assessor or triage,
        audit=record_audit,
        recommendations=FileAssessmentCache(),
        caller_thread=os.environ.get("CODEX_THREAD_ID"),
        clock=time.time,
        conversation=native_conversation(native_factory),
        read_context=lambda request: assessment_context(
            request.source, reader=context_reader or session_input
        ),
        store=FileStore(),
    )
    output = deliver_disposition(result, store=FileStore(), audit=record_audit)
    assert output is not None
    return output


def reassess(
    requirements: str,
    *,
    context_reader: Callable[[object], ProfileAssessmentInput] | None = None,
    assessor: AssessmentRunner | None = None,
    native_factory: Callable[[str], AppServerReader] | None = None,
) -> HookOutput:
    result = run_reassess(
        requirements,
        submitted_prompt,
        assessor=assessor or triage,
        audit=record_audit,
        recommendations=FileAssessmentCache(),
        caller_thread=os.environ.get("CODEX_THREAD_ID"),
        clock=time.time,
        conversation=native_conversation(native_factory),
        read_context=lambda request: assessment_context(
            request.source, reader=context_reader or session_input
        ),
        store=FileStore(),
        working_directory=os.getcwd,
    )
    output = deliver_disposition(result, store=FileStore(), audit=record_audit)
    assert output is not None
    return output


def can_continue_admitted_tool(event: dict[str, JsonValue]) -> bool:
    return continue_tool(
        tool_input(event),
        FileStore().snapshot(tool_input(event).thread_id),
        actions=NativeTransferTools(),
    )


def check_answer(request: str, context: str, answer: str) -> AnswerVerdict:
    return answer_check.classify_answer(
        request, context, answer, evaluator=answer_relevance.evaluate_relevance
    )
