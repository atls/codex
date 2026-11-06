"""Supported assessment and native Desktop handoff operations."""

import os
import subprocess
import time

from model_fit.application.assessment.contracts.decision import Decision
from model_fit.application.assessment.contracts.profile import Profile
from model_fit.application.assessment.contracts.request import AssessmentRequest
from model_fit.application.assessment.contracts.user_choice import UserChoice
from model_fit.application.assessment.failures.source_unavailable import (
    SourceUnavailable,
)
from model_fit.application.handoff.dependencies import Dependencies
from model_fit.application.handoff.lifecycle import Lifecycle
from model_fit.entrypoints.desktop.actions import NativeActions
from model_fit.entrypoints.desktop.input import (
    MISSING_DIRECTORY,
    answer_input,
    prompt_input,
    submitted_prompt,
    tool_input,
)
from model_fit.entrypoints.desktop.presentation import HookPresentation
from model_fit.infrastructure.assessment import relevance as answer_relevance
from model_fit.infrastructure.assessment.client import triage
from model_fit.infrastructure.audit.writer import record_audit
from model_fit.infrastructure.codex.conversation.gateway import ConversationGateway
from model_fit.infrastructure.codex.conversation.queries import (
    AppServerReader,
    queued_ids,
    session_input,
    unavailable_session_input,
)
from model_fit.infrastructure.codex.input.adapter import NativeInputs
from model_fit.infrastructure.codex.transport.connection import AppServerRPCError
from model_fit.infrastructure.handoff.recommendations.keyed import FileRecommendations
from model_fit.infrastructure.handoff.state.store import FileStore

__all__ = [
    "AssessmentRequest",
    "Decision",
    "Profile",
    "SourceUnavailable",
    "UserChoice",
    "assess",
    "assess_submitted",
    "reassess",
    "enqueue_handoff",
    "guard_replay_answer",
    "guard_tool",
    "prepare_handoff",
    "submit_prompt",
]


from model_fit.assessment import assess


def _handoff_dependencies(context_reader=None, assessor=None, native_factory=None):
    def conversation(cwd):
        if cwd is MISSING_DIRECTORY:
            raise KeyError("cwd")
        return ConversationGateway(
            (native_factory or AppServerReader)(cwd), queue_reader=queued_ids
        )

    return Dependencies(
        state=FileStore(),
        cache=FileRecommendations(),
        native=conversation,
        read_context=lambda request: (context_reader or session_input)(request.source),
        assess=assessor or triage,
        audit=record_audit,
        input=NativeInputs(),
        presentation=HookPresentation(),
        actions=NativeActions(),
        assessment_failure=(
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
            TimeoutError,
            subprocess.SubprocessError,
        ),
        context_failure=AppServerRPCError,
        context_reason=unavailable_session_input,
        queue_rejection=AppServerRPCError,
        relevance=answer_relevance.classify_answer,
        clock=time.time,
        caller_thread=os.environ.get("CODEX_THREAD_ID"),
        working_directory=os.getcwd,
    )


def prepare_handoff(event, *, context_reader=None, assessor=None, native_factory=None):
    return Lifecycle(
        _handoff_dependencies(context_reader, assessor, native_factory)
    ).prepare(prompt_input(event))


def enqueue_handoff(thread_id, turn_id, *, native_factory=None):
    return Lifecycle(_handoff_dependencies(native_factory=native_factory)).enqueue(
        thread_id, turn_id
    )


def guard_tool(event):
    return Lifecycle(_handoff_dependencies()).check_tool(tool_input(event))


def can_continue_admitted_tool(event):
    return Lifecycle(_handoff_dependencies()).can_continue_admitted_tool(
        tool_input(event)
    )


def guard_replay_answer(event, *, native_factory=None):
    return Lifecycle(_handoff_dependencies(native_factory=native_factory)).finish(
        answer_input(event)
    )


def submit_prompt(event, *, context_reader=None, assessor=None, native_factory=None):
    return Lifecycle(
        _handoff_dependencies(context_reader, assessor, native_factory)
    ).submit(prompt_input(event))


def assess_submitted(*, context_reader=None, assessor=None, native_factory=None):
    return Lifecycle(
        _handoff_dependencies(context_reader, assessor, native_factory)
    ).assess_submitted(submitted_prompt)


def reassess(
    requirements: str, *, context_reader=None, assessor=None, native_factory=None
):
    return Lifecycle(
        _handoff_dependencies(context_reader, assessor, native_factory)
    ).reassess(requirements, submitted_prompt)
