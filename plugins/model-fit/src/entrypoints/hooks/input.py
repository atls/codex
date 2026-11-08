from model_fit.autoswitch.requests.answer_check import AnswerCheck
from model_fit.autoswitch.requests.prompt import Prompt
from model_fit.autoswitch.requests.tool_check import ToolCheck
from model_fit.infrastructure.adapters.codex.identity import executor_thread_id

MISSING_DIRECTORY = object()


def prompt_input(native):
    return Prompt(
        executor_thread_id(native),
        native["turn_id"],
        native["prompt"],
        native.get("cwd", MISSING_DIRECTORY),
        native.get("model"),
        native,
        session_id=native["session_id"],
    )


def tool_input(native):
    return ToolCheck(executor_thread_id(native), native.get("turn_id"), native)


def answer_input(native):
    thread = executor_thread_id(native)
    return AnswerCheck(
        thread,
        native.get("turn_id"),
        native.get("last_assistant_message"),
        native.get("stop_hook_active"),
        native.get("cwd", MISSING_DIRECTORY),
        native,
    )


def submitted_prompt(pending, text):
    return prompt_input(
        {
            "session_id": pending.get("root_session_id", pending["thread_id"]),
            "agent_id": pending.get("agent_id"),
            "turn_id": pending["turn_id"],
            "cwd": pending["working_directory"],
            "model": pending["active_model"],
            "prompt": text,
        }
    )
