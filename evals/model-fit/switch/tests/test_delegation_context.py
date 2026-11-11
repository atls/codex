from vector_prime.application.assessment.types.context import ContextSource
import unittest
from unittest.mock import MagicMock, patch

import vector_prime.infrastructure.adapters.codex.history as queries
from vector_prime.application.assessment.helpers.context import recent_context

DELEGATION = {
    "type": "functionCallOutput",
    "name": "send_message_to_thread",
    "namespace": "codex_app",
    "output": "<codex_delegation><source_thread_id>sender</source_thread_id><input>Retire the old cluster; preserve DNS, media, archives and state access</input></codex_delegation>",
}


class DelegationContextTests(unittest.TestCase):
    def test_received_task_is_context_without_becoming_user_authorization(self):
        context = recent_context(
            "This is my instruction; execute it",
            [{"id": "previous", "items": [DELEGATION]}],
        )
        self.assertIn("Retire the old cluster", context or "")
        self.assertIn("another agent", context.casefold())
        self.assertNotIn("User: <codex_delegation>", context)

    def test_summary_only_reply_is_hydrated_through_all_native_item_pages(self):
        app = MagicMock()
        app.__enter__.return_value = app
        app.call.side_effect = [
            {"thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}},
            {
                "data": [
                    {"id": "current", "items": []},
                    {
                        "id": "previous",
                        "items": [
                            {"type": "agentMessage", "text": "Received task context"}
                        ],
                    },
                ]
            },
            {"data": [{"item": {"type": "reasoning"}}], "nextCursor": "more"},
            {"data": [{"item": DELEGATION}], "nextCursor": None},
        ]
        with patch.object(queries, "AppServerReader", return_value=app):
            request = queries.session_input(
                ContextSource(
                    "thread",
                    "current",
                    "This is my instruction; execute it",
                    "/fixture",
                    "gpt-6-luna",
                )
            )
        self.assertIn("preserve DNS, media", request["context"])
        self.assertEqual(app.call.call_args_list[-1].args[1]["cursor"], "more")

    def test_arbitrary_function_output_is_not_delegated_work(self):
        for changed in [
            {"namespace": "other"},
            {"name": "read_thread"},
            {"type": "commandExecution"},
        ]:
            with self.subTest(changed=changed):
                context = recent_context(
                    "continue", [{"items": [{**DELEGATION, **changed}]}]
                )
                self.assertIsNone(context)

    def test_context_read_does_not_silently_accept_repeated_item_cursor(self):
        app = MagicMock()
        app.__enter__.return_value = app
        app.call.side_effect = [
            {"thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}},
            {
                "data": [
                    {
                        "id": "previous",
                        "items": [{"type": "agentMessage", "text": "Received context"}],
                    }
                ]
            },
            {"data": [], "nextCursor": "again"},
            {"data": [], "nextCursor": "again"},
        ]
        with (
            patch.object(queries, "AppServerReader", return_value=app),
            self.assertRaises(ValueError),
        ):
            queries.session_input(
                ContextSource(
                    "thread", "current", "Execute it", "/fixture", "gpt-6-luna"
                )
            )

    def test_historical_context_excludes_turns_newer_than_source(self):
        app = MagicMock()
        app.__enter__.return_value = app

        def user(text):
            return {"type": "userMessage", "content": [{"type": "text", "text": text}]}

        app.call.side_effect = [
            {"thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}},
            {
                "data": [
                    {"id": "newer", "items": [user("FUTURE TASK")]},
                    {"id": "current", "items": [user("Execute it")]},
                    {"id": "older", "items": [user("CURRENT WORK")]},
                ]
            },
        ]
        with patch.object(queries, "AppServerReader", return_value=app):
            r = queries.session_input(
                ContextSource(
                    "thread", "current", "Execute it", "/fixture", "gpt-6-luna"
                )
            )
        self.assertIn("CURRENT WORK", r["context"])
        self.assertNotIn("FUTURE TASK", r["context"])
