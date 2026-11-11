import unittest

from vector_prime.application.handoff.control_message import (
    CONTROL_PROMPT,
    CONTROL_PROMPTS,
)
from vector_prime.application.switch.admission.types.input import ToolAdmissionInput
from vector_prime.entrypoints.hooks.tool_action import NativeTransferTools
from vector_prime.application.assessment.helpers.context import recent_context


class ControlMessageCompatibilityTests(unittest.TestCase):
    def test_current_and_legacy_switches_keep_thread_and_profile_bounds(self):
        state = {"target_model": "fixture-model", "target_effort": "medium"}
        for marker in CONTROL_PROMPTS:
            with self.subTest(marker=marker):
                args = {
                    "threadId": "thread",
                    "model": "fixture-model",
                    "thinking": "medium",
                    "prompt": marker,
                }
                source = {
                    "tool_name": "mcp__codex_app__send_message_to_thread",
                    "tool_input": args,
                }
                event = ToolAdmissionInput("thread", "turn", source)
                self.assertTrue(
                    NativeTransferTools().matches_profile_switch(event, state)
                )
                args["threadId"] = "foreign"
                self.assertFalse(
                    NativeTransferTools().matches_profile_switch(event, state)
                )
                args["threadId"] = "thread"
                args["model"] = "other-profile"
                self.assertFalse(
                    NativeTransferTools().matches_profile_switch(event, state)
                )
        self.assertEqual(
            CONTROL_PROMPT, "Model Fit: complete the technical request handoff"
        )

    def test_control_turns_do_not_displace_actual_work_in_context(self):
        def turn(identifier, text):
            return {
                "id": identifier,
                "items": [
                    {"type": "userMessage", "content": [{"type": "text", "text": text}]}
                ],
            }

        turns = [
            turn("work", "Preserve the database and media"),
            *[turn(str(i), marker) for i, marker in enumerate(CONTROL_PROMPTS)],
        ]
        context = recent_context("continue", turns, control_prompt=CONTROL_PROMPTS)
        self.assertIn("Preserve the database and media", context)
        for marker in CONTROL_PROMPTS:
            self.assertNotIn(marker, context)


class TransferRouteTests(unittest.TestCase):
    def test_mcp_route_is_explicit_and_dynamic_route_does_not_authorize_transfer(self):
        import os
        import tempfile
        import time
        from unittest.mock import patch
        from vector_prime.entrypoints.hooks import instructions, operations
        from vector_prime.infrastructure.adapters.filesystem.state import (
            state_path,
            write_state,
        )

        state = {
            "phase": "ready",
            "created_at": int(time.time()),
            "source_turn_id": "source",
            "prompt": "fixture work",
            "prompt_digest": "fixture",
            "target_model": "fixture-model",
            "target_effort": "medium",
            "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
            "official_guidance": "fixture guidance",
            "task_inference": "fixture inference",
        }
        context = instructions.control_context("thread", "source", state)[
            "hookSpecificOutput"
        ]["additionalContext"]
        self.assertIn("mcp__codex_app__send_message_to_thread", context)
        self.assertIn("Use the codex_app MCP server", context)
        arguments = {
            "threadId": "thread",
            "model": "fixture-model",
            "thinking": "medium",
            "prompt": CONTROL_PROMPT,
        }
        with (
            tempfile.TemporaryDirectory() as home,
            patch.dict(os.environ, {"CODEX_HOME": home}),
        ):
            path = state_path("thread")
            path.parent.mkdir(parents=True)
            write_state(path, state)
            before = path.read_bytes()
            event = {
                "session_id": "thread",
                "turn_id": "source",
                "tool_name": "send_message_to_thread",
                "tool_input": arguments,
            }
            with patch.object(operations, "AppServerReader") as reader:
                rejected = operations.guard_tool(event)
                self.assertEqual(
                    rejected["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                self.assertEqual(path.read_bytes(), before)
                self.assertIsNone(
                    operations.guard_tool(
                        {**event, "tool_name": "mcp__codex_app__send_message_to_thread"}
                    )
                )
                reader.assert_not_called()
