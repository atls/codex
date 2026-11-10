import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from model_fit.application.handoff.control_message import CONTROL_PROMPT
from model_fit.entrypoints.hooks.events.dispatch import handle_event
from model_fit.infrastructure.adapters.filesystem.state import (
    read_state,
    state_path,
    write_state,
)


class PreparationAdmissionTests(unittest.TestCase):
    def test_incomplete_preparation_cannot_authorize_a_profile_change(self):
        thread_id, turn_id = "fixture-thread", "fixture-turn"
        with (
            tempfile.TemporaryDirectory() as home,
            patch.dict(os.environ, {"CODEX_HOME": home}),
        ):
            path = state_path(thread_id)
            path.parent.mkdir(parents=True)
            write_state(
                path,
                {
                    "phase": "ready",
                    "source_turn_id": turn_id,
                    "target_model": "fixture-model",
                    "target_effort": "low",
                    "created_at": 1,
                    "prompt_digest": "a" * 64,
                },
            )
            original = path.read_bytes()
            output = io.StringIO()
            with redirect_stdout(output):
                handle_event(
                    expected_thread=thread_id,
                    event={
                        "session_id": thread_id,
                        "turn_id": turn_id,
                        "hook_event_name": "PreToolUse",
                        "tool_name": "mcp__codex_app__send_message_to_thread",
                        "tool_input": {
                            "threadId": thread_id,
                            "model": "fixture-model",
                            "thinking": "low",
                            "prompt": CONTROL_PROMPT,
                        },
                    },
                )
            response = json.loads(output.getvalue())
            self.assertEqual(
                response["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn("transfer_authorized_at", read_state(path))
