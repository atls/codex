"""Isolated Desktop handoff setup shared by scenario tests."""

import copy
import time
import unittest

import pytest
from unittest.mock import patch

from fixtures.autoswitch.assessment import evaluate_request
from vector_prime.entrypoints.hooks import operations
import vector_prime.application.submission.helpers.content as HANDOFF_INPUT
import vector_prime.infrastructure.adapters.filesystem.state as HANDOFF_STATE


class DesktopHandoffCase(unittest.TestCase):
    thread_id = "test-thread"

    turn_id = "test-turn"

    prompt = "Design a snapshot search engine"

    active = {"model": "gpt-6-luna", "effort": "low", "speed": None}

    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": thread_id,
        "turn_id": turn_id,
        "cwd": "/tmp",
        "model": "gpt-6-luna",
        "prompt": prompt,
    }

    recommendation = {
        "decision": "recommend_stronger",
        "active_model": "gpt-6-luna",
        "active_effort": "low",
        "active_speed": None,
        "recommended_model": "gpt-6-sol",
        "recommended_effort": "medium",
        "recommended_speed": None,
        "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
        "official_guidance": "Select the profile for the task.",
        "task_inference": "Design is needed.",
        "reason": "Deeper reasoning is needed.",
    }

    @pytest.fixture(autouse=True)
    def isolated_codex(self, codex_home, monkeypatch):
        self.home = codex_home
        monkeypatch.setenv("CODEX_THREAD_ID", self.thread_id)

    def source_response(self, content=None):
        return {
            "data": [
                {
                    "item": {
                        "type": "userMessage",
                        "content": content or [{"type": "text", "text": self.prompt}],
                    }
                }
            ],
            "nextCursor": None,
        }

    def queue_receipt(self, content=None):
        return {
            "queuedSubmission": {
                "id": "queued-1",
                "input": copy.deepcopy(
                    content or [{"type": "text", "text": self.prompt}]
                ),
            }
        }

    def stage(self, target_model="gpt-6-sol"):
        state = {
            "phase": "ready",
            "created_at": int(time.time()),
            "source_turn_id": self.turn_id,
            "prompt": self.prompt,
            "prompt_digest": HANDOFF_INPUT.prompt_digest(self.prompt),
            "target_model": target_model,
            "target_effort": "medium",
            "official_source_url": self.recommendation["official_source_url"],
            "official_guidance": self.recommendation["official_guidance"],
            "task_inference": self.recommendation["task_inference"],
        }
        path = HANDOFF_STATE.state_path(self.thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        HANDOFF_STATE.write_state(path, state)
        return path

    def prepare_ready(self, event):
        with (
            patch.object(
                operations,
                "session_input",
                return_value={"task": event["prompt"], "active_profile": self.active},
            ),
            patch.object(operations, "triage", return_value=self.recommendation),
            patch.object(operations, "AppServerReader") as reader,
        ):
            reader.return_value.__enter__.return_value.call.return_value = {
                "data": [],
                "nextCursor": None,
            }
            return evaluate_request(event)

    def stage_replay(self, content=None):
        content = content or [{"type": "text", "text": self.prompt}]
        queued = copy.deepcopy(content)
        path = self.stage()
        state = HANDOFF_STATE.read_state(path)
        state.pop("prompt")
        state.update(
            phase="queued",
            replay_turn_id="replay-turn",
            queued_input_digest=HANDOFF_INPUT.input_digest(queued),
        )
        HANDOFF_STATE.write_state(path, state)
        return (content, queued)
