"""Dispatch user-level lifecycle hooks to the event's Desktop chat."""

from __future__ import annotations

import json
import os
import sys

from model_fit.entrypoints.desktop.activation import (
    automatic_allowed,
    inactive_output,
    record_unavailable,
)
from model_fit.entrypoints.desktop.lifecycle import handle_lifecycle
from model_fit.infrastructure.codex.identity import executor_thread_id


def dispatch_hook() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw)
        if not isinstance(event, dict):
            return 0
        try:
            thread_id = executor_thread_id(event)
        except ValueError:
            return 0
        admitted = automatic_allowed(
            event.get("hook_event_name", ""), event.get("cwd") or os.getcwd()
        )
        if admitted is not True:
            if admitted is None:
                record_unavailable(
                    thread_id, event.get("turn_id"), event.get("hook_event_name", "")
                )
            output = inactive_output(event, admitted)
            if output is not None:
                print(json.dumps(output, ensure_ascii=False))
            return 0
        return handle_lifecycle(event=event, expected_thread=thread_id)
    except (OSError, ValueError, TypeError) as error:
        print(f"Model Fit global hook failed ({type(error).__name__})", file=sys.stderr)
        return 1
