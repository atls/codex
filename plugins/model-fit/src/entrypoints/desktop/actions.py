import shlex
import sys
from pathlib import Path
from typing import Any, cast

from .configuration import PROFILE_SWITCH_TOOLS
from .instructions import CONTROL_PROMPT, assessment_command, queue_command


class NativeActions:
    @staticmethod
    def _command_arguments(value: object) -> list[str] | None:
        if not isinstance(value, str):
            return None
        try:
            command = shlex.split(value)
            if not command:
                return None
            candidate, active = Path(command[0]), Path(sys.executable)
            if (
                not candidate.is_absolute()
                or candidate.parent.resolve() != active.parent.resolve()
                or not candidate.samefile(active)
            ):
                return None
        except (OSError, ValueError):
            return None
        return command[1:]

    def matches_assessment(self, request):
        native = cast(dict[str, Any], request.source)
        arguments = native.get("tool_input")
        return (
            isinstance(arguments, dict)
            and native.get("tool_name") == "Bash"
            and self._command_arguments(arguments.get("command"))
            == shlex.split(assessment_command())[1:]
        )

    def matches_profile_switch(self, request, state):
        native = cast(dict[str, Any], request.source)
        arguments = native.get("tool_input")
        return (
            isinstance(arguments, dict)
            and native.get("tool_name") in PROFILE_SWITCH_TOOLS
            and all(
                (
                    arguments.get("threadId") == request.thread_id,
                    arguments.get("model") == state["target_model"],
                    arguments.get("thinking") == state["target_effort"],
                    arguments.get("prompt") == CONTROL_PROMPT,
                )
            )
        )

    def matches_queue(self, request, state):
        native = cast(dict[str, Any], request.source)
        arguments = native.get("tool_input")
        return (
            isinstance(arguments, dict)
            and native.get("tool_name") == "Bash"
            and self._command_arguments(arguments.get("command"))
            == shlex.split(queue_command(request.thread_id, state["source_turn_id"]))[
                1:
            ]
        )

    def bound_transfer_input(self, request, state):
        native = cast(dict[str, Any], request.source)
        arguments = native.get("tool_input")
        if not isinstance(arguments, dict):
            return None
        if (
            native.get("tool_name") in PROFILE_SWITCH_TOOLS
            and arguments.get("prompt") == CONTROL_PROMPT
            and arguments.get("model") == state["target_model"]
            and arguments.get("thinking") == state["target_effort"]
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
        command = self._command_arguments(arguments["command"])
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

    def matches_transfer(self, request):
        native = cast(dict[str, Any], request.source)
        arguments = native.get("tool_input")
        if not isinstance(arguments, dict):
            return False
        if (
            native.get("tool_name") in PROFILE_SWITCH_TOOLS
            and arguments.get("prompt") == CONTROL_PROMPT
        ):
            return True
        if native.get("tool_name") != "Bash" or not isinstance(
            arguments.get("command"), str
        ):
            return False
        command = self._command_arguments(arguments["command"])
        if command is None:
            return False
        expected = shlex.split(queue_command("current", "source"))[1:]
        return (
            len(command) == len(expected)
            and command[:-3] == expected[:-3]
            and command[-2] == expected[-2]
        )
