"""Exercise transfer commands through public API with real persisted state."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import vector_prime.entrypoints.hooks.operations as api
from vector_prime.infrastructure.adapters.filesystem.state import read_state, state_path


class TransferJourneyTests(unittest.TestCase):
    def test_transfer_preserves_input_replays_once_and_checks_completion(self):
        thread, source, replay = ("journey-thread", "source-turn", "replay-turn")
        content = [
            {"type": "text", "text": "Analyze the task", "text_elements": []},
            {"type": "image", "url": "fixture-image", "detail": None},
        ]
        event = {
            "session_id": thread,
            "turn_id": source,
            "prompt": "Analyze the task",
            "cwd": "/tmp",
            "model": "gpt-6-luna",
        }
        request = {
            "task": event["prompt"],
            "active_profile": {"model": "gpt-6-luna", "effort": "low", "speed": None},
        }
        decision = {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "active_speed": None,
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "high",
            "recommended_speed": None,
            "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
            "official_guidance": "fixture guidance",
            "task_inference": "fixture task",
        }
        queued = []
        profile = {"model": "gpt-6-luna", "reasoningEffort": "low"}

        def rpc(method, params, timeout):
            if method == "thread/queue/list":
                return {"data": [], "nextCursor": None}
            if method == "thread/read":
                return {"thread": profile}
            if method == "thread/items/list":
                value = content if params["turnId"] == source else queued[0]
                return {
                    "data": [
                        {
                            "item": {
                                "type": "userMessage",
                                "id": "native-message",
                                "clientId": "composer"
                                if params["turnId"] == source
                                else source,
                                "content": value,
                            }
                        }
                    ],
                    "nextCursor": None,
                }
            if method == "thread/queue/add":
                queued.append(params["input"])
                return {"queuedSubmission": {"id": "receipt", "input": params["input"]}}
            raise AssertionError(method)

        reader = MagicMock()
        reader.__enter__.return_value.call.side_effect = rpc
        with (
            tempfile.TemporaryDirectory() as home,
            patch.dict(os.environ, {"CODEX_HOME": home, "CODEX_THREAD_ID": thread}),
        ):
            output = api.submit_prompt(
                event,
                context_reader=lambda e: request,
                assessor=lambda r: decision,
                native_factory=lambda cwd: reader,
            )
            self.assertIn("hookSpecificOutput", output)
            api.assess_submitted(
                context_reader=lambda e: request,
                assessor=lambda r: decision,
                native_factory=lambda cwd: reader,
            )
            self.assertEqual(read_state(state_path(thread))["phase"], "ready")
            profile.update(model="gpt-6.1-sol", reasoningEffort="high")
            self.assertEqual(
                api.enqueue_handoff(thread, source, native_factory=lambda cwd: reader)[
                    "status"
                ],
                "queued",
            )
            self.assertEqual(queued[0], content)
            self.assertEqual(
                api.enqueue_handoff(thread, source, native_factory=lambda cwd: reader)[
                    "status"
                ],
                "already_queued",
            )
            self.assertEqual(len(queued), 1)
            replay_event = {
                **event,
                "turn_id": replay,
                "prompt": queued[0][0]["text"],
                "model": "gpt-6.1-sol",
            }
            selected = {
                "active_profile": {
                    "model": "gpt-6.1-sol",
                    "effort": "high",
                    "speed": None,
                }
            }
            output = api.submit_prompt(
                replay_event,
                context_reader=lambda e: selected,
                assessor=lambda r: self.fail("Replay was reassessed"),
                native_factory=lambda cwd: reader,
            )
            output = api.assess_submitted(
                context_reader=lambda e: selected,
                assessor=lambda r: self.fail("Replay was reassessed"),
                native_factory=lambda cwd: reader,
            )
            self.assertIn(
                "model fit handoff is complete",
                output["hookSpecificOutput"]["additionalContext"].casefold(),
            )
            self.assertIsNone(
                api.guard_tool(
                    {
                        **replay_event,
                        "tool_name": "Bash",
                        "tool_input": {"command": "pwd"},
                    }
                )
            )
            self.assertIsNone(
                api.guard_replay_answer(
                    {**replay_event, "last_assistant_message": "Answer"},
                    native_factory=lambda cwd: reader,
                )
            )
            self.assertEqual(read_state(state_path(thread))["replay_turn_id"], replay)
            self.assertEqual(len(queued), 1)
            audits = [
                json.loads(line)["outcome"]
                for line in (
                    Path(home) / ".tmp/model-fit-hook-audit" / f"{thread}.jsonl"
                )
                .read_text()
                .splitlines()
            ]
            self.assertIn("auto_handoff", audits)
            self.assertIn("auto_replay", audits)
            self.assertIn("auto_stop_multimodal_unchecked", audits)

    def test_unknown_queue_outcome_blocks_retry_and_preserves_attempt(self):
        event = {
            "session_id": "journey-thread",
            "turn_id": "source-turn",
            "prompt": "task",
            "cwd": "/tmp",
            "model": "gpt-6-luna",
        }
        request = {
            "task": "task",
            "active_profile": {"model": "gpt-6-luna", "effort": "low", "speed": None},
        }
        decision = {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "active_speed": None,
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "high",
            "recommended_speed": None,
            "official_source_url": "https://developers.openai.com/api/docs/guides/reasoning",
            "official_guidance": "fixture",
            "task_inference": "fixture",
        }
        reader = MagicMock()
        app = reader.__enter__.return_value
        with (
            tempfile.TemporaryDirectory() as home,
            patch.dict(
                os.environ, {"CODEX_HOME": home, "CODEX_THREAD_ID": "journey-thread"}
            ),
        ):
            app.call.return_value = {"data": [], "nextCursor": None}
            api.submit_prompt(
                event,
                context_reader=lambda e: request,
                assessor=lambda r: decision,
                native_factory=lambda cwd: reader,
            )
            app.call.side_effect = [
                {
                    "data": [
                        {
                            "item": {
                                "id": "native-message",
                                "type": "userMessage",
                                "content": [{"type": "text", "text": "task"}],
                            }
                        }
                    ],
                    "nextCursor": None,
                },
                {"data": [], "nextCursor": None},
                {
                    "thread": {
                        "model": request["active_profile"]["model"],
                        "reasoningEffort": request["active_profile"]["effort"],
                    }
                },
            ]
            api.assess_submitted(
                context_reader=lambda e: request,
                assessor=lambda r: decision,
                native_factory=lambda cwd: reader,
            )
            app.call.side_effect = [
                {"thread": {"model": "gpt-6.1-sol", "reasoningEffort": "high"}},
                {
                    "data": [
                        {
                            "item": {
                                "type": "userMessage",
                                "content": [{"type": "text", "text": "task"}],
                            }
                        }
                    ],
                    "nextCursor": None,
                },
                TimeoutError("receipt unavailable"),
            ]
            with self.assertRaises(TimeoutError):
                api.enqueue_handoff(
                    "journey-thread", "source-turn", native_factory=lambda cwd: reader
                )
            path = state_path("journey-thread")
            saved = path.read_bytes()
            self.assertEqual(read_state(path)["phase"], "attempting")
            with self.assertRaisesRegex(RuntimeError, "unknown outcome"):
                api.enqueue_handoff(
                    "journey-thread", "source-turn", native_factory=lambda cwd: reader
                )
            blocked = api.submit_prompt(
                {**event, "turn_id": "next-turn"},
                context_reader=lambda e: self.fail("Blocked work was assessed"),
            )
            self.assertEqual(blocked["decision"], "block")
            self.assertEqual(path.read_bytes(), saved)
