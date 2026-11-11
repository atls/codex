import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from vector_prime.application.switch.lifecycle import abstain_assessment
from vector_prime.entrypoints.hooks.operations import guard_tool
from vector_prime.infrastructure.adapters.filesystem.state import (
    read_state,
    state_path,
    write_state,
)
from vector_prime.infrastructure.adapters.filesystem.store import FileStore


class AssessmentGenerationTests(unittest.TestCase):
    def test_zero_legacy_generation_can_recover_without_blocking_original_work(self):
        thread_id, turn_id = "fixture-thread", "fixture-turn"
        pending = {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "generation": 0,
            "status": "running",
        }
        with (
            tempfile.TemporaryDirectory() as home,
            patch.dict(os.environ, {"CODEX_HOME": home}),
        ):
            path = state_path(thread_id)
            path.parent.mkdir(parents=True)
            write_state(
                path,
                {
                    "phase": "submitted",
                    "source_turn_id": turn_id,
                    "assessment_generation": 0,
                    "pending_assessment": pending,
                },
            )
            with FileStore().transaction(thread_id) as slot:
                self.assertTrue(abstain_assessment(slot, pending))
            unavailable = Mock(side_effect=OSError("fixture source unavailable"))
            with patch(
                "vector_prime.entrypoints.hooks.operations.native_conversation",
                return_value=unavailable,
            ):
                self.assertIsNone(
                    guard_tool(
                        {
                            "session_id": thread_id,
                            "turn_id": turn_id,
                            "tool_name": "Bash",
                            "tool_input": {"command": "pwd"},
                        }
                    )
                )
            state = read_state(path)
            self.assertEqual(state["phase"], "passed")
            self.assertEqual(state["assessment_decision"], "unknown")
            self.assertEqual(state["assessment_generation"], 0)
            self.assertNotIn("pending_assessment", state)
