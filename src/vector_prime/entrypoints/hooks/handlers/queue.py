from __future__ import annotations
import json
import os
import subprocess
import sys
from vector_prime.entrypoints.hooks.operations import enqueue_handoff as enqueue
from vector_prime.application.handoff.exceptions.queue_rejected import QueueRejected
from vector_prime.infrastructure.adapters.filesystem.audit import (
    failure_location,
    record_audit,
)


def queue_handoff(thread_id: str, turn_id: str) -> int:
    audit_thread = (
        os.environ.get("CODEX_THREAD_ID") if thread_id == "current" else thread_id
    )
    audit_turn = None if turn_id == "source" else turn_id
    try:
        result = enqueue(thread_id, turn_id)
        if audit_thread:
            record_audit(
                audit_thread,
                audit_turn,
                f"auto_queue_{result['status']}",
                {"hook_event": "queue"},
            )
        print(json.dumps(result))
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        TimeoutError,
        subprocess.SubprocessError,
    ) as error:
        error_name = (
            "AppServerRPCError"
            if isinstance(error, QueueRejected)
            else type(error).__name__
        )
        if audit_thread:
            record_audit(
                audit_thread,
                audit_turn,
                f"auto_queue_error:{error_name}",
                {
                    "hook_event": "queue",
                    "reason_code": "queue_failed",
                    **failure_location(error),
                },
            )
        print(f"Model Fit queue failed ({error_name})", file=sys.stderr)
        return 1
