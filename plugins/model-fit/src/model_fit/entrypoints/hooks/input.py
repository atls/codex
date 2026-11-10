from model_fit.application.submission.types.json import JsonValue
from model_fit.application.submission.constraints.content import checked_object
from model_fit.application.assessment.decoding import required_text, optional_text
from model_fit.application.assessment.types.state import PendingAssessmentRecord
from model_fit.application.answer.types.input import ReplayAnswerInput
from model_fit.application.submission.types.input import SubmissionInput
from model_fit.application.switch.admission.types.input import ToolAdmissionInput
from model_fit.infrastructure.adapters.codex.identity import executor_thread_id
from model_fit.infrastructure.adapters.runtime.executable_identity import (
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


def submitted_prompt(pending: PendingAssessmentRecord, text: str) -> SubmissionInput:
    return prompt_input(
        checked_object(
            {
                "session_id": pending.get("root_session_id", pending["thread_id"]),
                "agent_id": pending.get("agent_id"),
                "turn_id": pending["turn_id"],
                "cwd": pending["working_directory"],
                "model": pending["active_model"],
                "prompt": text,
            }
        )
    )
