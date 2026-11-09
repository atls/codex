"""Apply automatic hook admission at the executable boundary."""

import subprocess
import sys

from model_fit.entrypoints.hooks.operations import can_continue_admitted_tool
from model_fit.entrypoints.hooks.response import inactive_hook
from model_fit.infrastructure.adapters.codex.hooks import hook_enabled
from model_fit.infrastructure.adapters.filesystem.audit import record_audit


def automatic_allowed(
    event_name: str, cwd: str, *, direct: bool = False
) -> bool | None:
    try:
        admitted = hook_enabled(event_name, cwd)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        TimeoutError,
        subprocess.SubprocessError,
    ) as error:
        print(
            f"Model Fit hook admission unavailable ({type(error).__name__})",
            file=sys.stderr,
        )
        return None
    return direct if admitted is None else admitted


def record_unavailable(
    thread_id: str | None, turn_id: str | None, event_name: str
) -> None:
    if thread_id:
        record_audit(
            thread_id,
            turn_id,
            "auto_hook_admission_unknown",
            {
                "hook_event": event_name,
                "reason_code": "automatic_admission_unavailable",
            },
        )


def inactive_output(event, admitted):
    continued = False
    if admitted is None and event.get("hook_event_name") == "PreToolUse":
        try:
            continued = can_continue_admitted_tool(event)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return inactive_hook(event, unavailable=admitted is None, admitted_tool=continued)
