import shlex
from model_fit.application.submission.types.json import JsonValue
from model_fit.application.submission.constraints.content import checked_object
from model_fit.application.switch.admission.types.input import ToolAdmissionInput
from model_fit.application.switch.state.types.record import HandoffStateRecord

from model_fit.application.handoff.control_message import (
    CONTROL_PROMPT,
    CONTROL_PROMPTS,
)
from model_fit.entrypoints.hooks.instructions import (
    assessment_command,
    queue_command,
)
from model_fit.entrypoints.hooks.native_contract import PROFILE_SWITCH_TOOLS


class NativeTransferTools:
    def matches_assessment(self, request: ToolAdmissionInput) -> bool:
        native = checked_object(request.source)
        arguments = native.get("tool_input")
        return (
            isinstance(arguments, dict)
            and native.get("tool_name") == "Bash"
            and (request.command_arguments == shlex.split(assessment_command())[1:])
        )

    def matches_profile_switch(
        self, request: ToolAdmissionInput, state: HandoffStateRecord
    ) -> bool:
        native = checked_object(request.source)
        arguments = native.get("tool_input")
        return (
            isinstance(arguments, dict)
            and native.get("tool_name") in PROFILE_SWITCH_TOOLS
            and all(
                (
                    arguments.get("threadId") == request.thread_id,
                    arguments.get("model") == state["target_model"],
                    arguments.get("thinking") == state["target_effort"],
                    arguments.get("prompt") in CONTROL_PROMPTS,
                )
            )
        )

    def matches_queue(
        self, request: ToolAdmissionInput, state: HandoffStateRecord
    ) -> bool:
        native = checked_object(request.source)
        arguments = native.get("tool_input")
        return (
            isinstance(arguments, dict)
            and native.get("tool_name") == "Bash"
            and (
                request.command_arguments
                == shlex.split(
                    queue_command(request.thread_id, state["source_turn_id"])
                )[1:]
            )
        )

    def bound_transfer_input(
        self, request: ToolAdmissionInput, state: HandoffStateRecord
    ) -> dict[str, JsonValue] | None:
        native = checked_object(request.source)
        arguments = native.get("tool_input")
        if not isinstance(arguments, dict):
            return None
        if (
            native.get("tool_name") in PROFILE_SWITCH_TOOLS
            and arguments.get("prompt") in CONTROL_PROMPTS
            and (arguments.get("model") == state["target_model"])
            and (arguments.get("thinking") == state["target_effort"])
        ):
            return {
                "threadId": request.thread_id,
                "model": state["target_model"],
                "thinking": state["target_effort"],
                "prompt": CONTROL_PROMPT,
            }
        if native.get("tool_name") != "Bash" or not isinstance(
            arguments.get("command"), str
        ):
            return None
        command = request.command_arguments
        if command is None:
            return None
        expected = shlex.split(
            queue_command(request.thread_id, state["source_turn_id"])
        )[1:]
        if (
            len(command) != len(expected)
            or command[:-3] != expected[:-3]
            or command[-2] != expected[-2]
        ):
            return None
        return {
            **arguments,
            "command": queue_command(request.thread_id, state["source_turn_id"]),
        }

    def matches_transfer(self, request: ToolAdmissionInput) -> bool:
        native = checked_object(request.source)
        arguments = native.get("tool_input")
        if not isinstance(arguments, dict):
            return False
        if (
            native.get("tool_name") in PROFILE_SWITCH_TOOLS
            and arguments.get("prompt") in CONTROL_PROMPTS
        ):
            return True
        if native.get("tool_name") != "Bash" or not isinstance(
            arguments.get("command"), str
        ):
            return False
        command = request.command_arguments
        if command is None:
            return False
        expected = shlex.split(queue_command("current", "source"))[1:]
        return (
            len(command) == len(expected)
            and command[:-3] == expected[:-3]
            and (command[-2] == expected[-2])
        )
