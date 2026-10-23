"""Shared isolated fixtures for Model Fit hook tests."""

import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins/model-fit/skills/model-fit/scripts"
sys.path.insert(0, str(SCRIPTS))
from model_fit import input as INPUT, state as STATE

SPEC = importlib.util.spec_from_file_location("hook", SCRIPTS / "hook.py")
AUTO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTO)


class AutoSwitchCase(unittest.TestCase):
    thread_id = "test-thread"
    turn_id = "test-turn"
    prompt = "Спроектируй поисковик по снимкам"
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
        "official_guidance": "Выбирайте профиль по задаче.",
        "task_inference": "Нужно проектирование.",
        "reason": "Нужна глубина.",
    }

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict(
            os.environ,
            {
                "CODEX_HOME": self.temporary.name,
                "CODEX_THREAD_ID": self.thread_id,
            },
        )
        self.environment.start()
        self.nonce = patch.object(AUTO.secrets, "token_hex", return_value="nonce")
        self.nonce.start()

    def tearDown(self):
        self.nonce.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def source_response(self, content=None):
        return {
            "data": [
                {
                    "item": {
                        "type": "userMessage",
                        "content": content
                        or [
                            {"type": "text", "text": self.prompt},
                        ],
                    }
                }
            ],
            "nextCursor": None,
        }

    def queue_receipt(self, content=None):
        return {
            "queuedSubmission": {
                "id": "queued-1",
                "input": INPUT.replay_input(
                    content or [{"type": "text", "text": self.prompt}],
                    "nonce",
                ),
            }
        }

    def stage(self):
        state = {
            "phase": "ready",
            "created_at": int(time.time()),
            "source_turn_id": self.turn_id,
            "prompt": self.prompt,
            "prompt_digest": INPUT.prompt_digest(self.prompt),
            "target_model": "gpt-6-sol",
            "target_effort": "medium",
            "official_source_url": self.recommendation["official_source_url"],
            "official_guidance": self.recommendation["official_guidance"],
            "task_inference": self.recommendation["task_inference"],
        }
        path = STATE.state_path(self.thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_state(path, state)
        return path

    def stage_replay(self, content=None):
        content = content or [{"type": "text", "text": self.prompt}]
        queued = INPUT.replay_input(content, "nonce")
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        state.update(
            phase="queued",
            replay_turn_id="replay-turn",
            queued_input_digest=INPUT.input_digest(queued),
        )
        STATE.write_state(path, state)
        return content, queued
