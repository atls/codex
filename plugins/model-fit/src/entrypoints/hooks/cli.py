"Desktop hooks and queued profile handoff."

import argparse
import json
import os
from pathlib import Path

from model_fit.entrypoints.hooks.activation import automatic_allowed, record_unavailable
from model_fit.entrypoints.hooks.dispatch import dispatch_hook
from model_fit.entrypoints.hooks.instructions import (
    admission_unavailable_context,
    inactive_context,
)
from model_fit.entrypoints.hooks.lifecycle import (
    assess_current,
    handle_lifecycle,
    queue_handoff,
)
from model_fit.entrypoints.hooks.prompt import handle_prompt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("hook", help="Dispatch a user-level lifecycle hook")
    commands.add_parser("lifecycle", help="Handle a thread-scoped lifecycle hook")
    commands.add_parser("assess", help="Assess the accepted native input of this turn")
    refresh = commands.add_parser(
        "reassess", help="Reassess native input after discovering changed requirements"
    )
    refresh.add_argument("--requirements-file", type=Path, required=True)
    commands.add_parser("prompt", help="Assess a prompt without automatic handoff")
    queue = commands.add_parser("queue", help="Queue an assessed handoff")
    queue.add_argument("--thread-id", required=True)
    queue.add_argument("--turn-id", required=True)
    args = parser.parse_args(argv)
    if args.command in {"assess", "reassess", "queue", "prompt"}:
        permitted = automatic_allowed(
            "UserPromptSubmit", os.getcwd(), direct=args.command == "prompt"
        )
        if args.command == "queue":
            permitted = permitted and automatic_allowed("PreToolUse", os.getcwd())
        if not permitted:
            if permitted is None:
                record_unavailable(
                    os.environ.get("CODEX_THREAD_ID"), None, args.command
                )
            context = (
                inactive_context()
                if permitted is False
                else admission_unavailable_context()
            )
            print(
                json.dumps(
                    context
                    if args.command != "queue"
                    else {
                        "status": "disabled" if permitted is False else "unavailable"
                    },
                    ensure_ascii=False,
                )
            )
            return 1 if args.command == "queue" else 0
    if args.command == "hook":
        return dispatch_hook()
    if args.command == "reassess":
        try:
            requirements = args.requirements_file.read_text()
        except (OSError, UnicodeError) as error:
            print(json.dumps({"status": "failed", "error": type(error).__name__}))
            return 1
        return assess_current(check_admission=True, requirements=requirements)
    if args.command == "assess":
        return assess_current(check_admission=True)
    if args.command == "prompt":
        return handle_prompt()
    if args.command == "queue":
        return queue_handoff(args.thread_id, args.turn_id)
    return handle_lifecycle(check_admission=True)


if __name__ == "__main__":
    raise SystemExit(main())
