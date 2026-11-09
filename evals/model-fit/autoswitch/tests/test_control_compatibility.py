import unittest

from model_fit.autoswitch.handoff.control_message import CONTROL_PROMPT, CONTROL_PROMPTS
from model_fit.autoswitch.admission.input import ToolAdmissionInput
from model_fit.infrastructure.adapters.hooks.tools import NativeTransferTools
from model_fit.submission.context import recent_context


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
