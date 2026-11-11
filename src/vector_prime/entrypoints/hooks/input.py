from vector_prime.application.assessment.types.context import ContextSource
from vector_prime.application.submission.types.json import JsonValue
from vector_prime.application.submission.decoding import checked_object
from vector_prime.application.assessment.decoding import required_text, optional_text
from vector_prime.application.assessment.types.state import PendingAssessment
from vector_prime.application.answer.types.input import ReplayAnswerInput
from vector_prime.application.submission.types.input import SubmissionInput
from vector_prime.application.switch.admission.types.input import ToolAdmissionInput
from vector_prime.entrypoints.hooks.events.identity import executor_thread_id
from vector_prime.infrastructure.adapters.runtime.executable_identity import (
    verified_python_arguments,
)


def prompt_input(native: dict[str, JsonValue]) -> SubmissionInput:
    return SubmissionInput(
        executor_thread_id(native),
        required_text(native["turn_id"]),
        required_text(native["prompt"]),
        optional_text(native.get("cwd")),
        optional_text(native.get("model")),
        native,
        session_id=required_text(native["session_id"]),
    )


def context_input(native: dict[str, JsonValue], thread_id: str) -> ContextSource:
    return ContextSource(
        thread_id,
        optional_text(native.get("turn_id")),
        required_text(native.get("prompt")),
        optional_text(native.get("cwd")),
        optional_text(native.get("model")),
    )


def assessment_source(event: SubmissionInput) -> ContextSource:
    return ContextSource(
        event.thread_id,
        event.turn_id,
        event.text,
        event.working_directory,
        event.active_model,
    )


def tool_input(native: dict[str, JsonValue]) -> ToolAdmissionInput:
    arguments = native.get("tool_input")
    command = arguments.get("command") if isinstance(arguments, dict) else None
    return ToolAdmissionInput(
        executor_thread_id(native),
        optional_text(native.get("turn_id")),
        native,
        verified_python_arguments(command)
        if native.get("tool_name") == "Bash"
        else None,
    )


def answer_input(native: dict[str, JsonValue]) -> ReplayAnswerInput:
    thread = executor_thread_id(native)
    return ReplayAnswerInput(
        thread,
        optional_text(native.get("turn_id")),
        optional_text(native.get("last_assistant_message")),
        native.get("stop_hook_active") is True,
        optional_text(native.get("cwd")),
        native,
    )


def submitted_prompt(pending: PendingAssessment, text: str) -> SubmissionInput:
    return prompt_input(
        checked_object(
            {
                "session_id": pending.root_session_id
                if pending.root_session_id is not None
                else pending.thread_id,
                "agent_id": pending.agent_id,
                "turn_id": pending.turn_id,
                "cwd": pending.working_directory,
                "model": pending.active_model,
                "prompt": text,
            }
        )
    )
