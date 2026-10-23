"""Model Fit hook regression checks."""

import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hook_case import AUTO, INPUT, STATE, AutoSwitchCase


class ReplayLifecycleTests(AutoSwitchCase):
    def test_interrupted_source_with_removed_queue_item_releases_new_request(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        state.update(
            phase="queued",
            queued_submission_id="queued-1",
            queued_at=100,
            queued_prompt_digest=INPUT.prompt_digest(
                INPUT.replay_prompt(self.prompt, "nonce")
            ),
        )
        STATE.write_state(path, state)
        new_event = dict(self.event, turn_id="new-turn")
        with (
            patch.object(
                AUTO,
                "session_input",
                return_value={
                    "task": self.prompt,
                    "active_profile": self.active,
                },
            ),
            patch.object(AUTO, "triage", return_value={"decision": "keep"}),
            patch.object(AUTO, "AppServerReader") as reader,
        ):
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"data": [], "nextCursor": None},
                {
                    "data": [
                        {
                            "id": self.turn_id,
                            "startedAt": 99,
                            "status": "interrupted",
                            "completedAt": None,
                        }
                    ],
                    "nextCursor": None,
                },
                {
                    "data": [{"id": self.turn_id, "status": "interrupted"}],
                    "nextCursor": None,
                },
            ]
            self.assertIsNone(AUTO.prepare(new_event))
            self.assertEqual(
                [call.args[0] for call in app.call.call_args_list],
                [
                    "thread/queue/list",
                    "thread/turns/list",
                    "thread/turns/list",
                ],
            )
        self.assertEqual(STATE.read_state(path)["phase"], "passed")

    def test_dequeued_request_runs_only_on_target_profile(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        queued_prompt = INPUT.replay_prompt(self.prompt, "nonce")
        state.update(
            phase="queued",
            queued_submission_id="queued-1",
            queued_at=100,
            queued_prompt_digest=INPUT.prompt_digest(queued_prompt),
        )
        STATE.write_state(path, state)
        replay_event = dict(self.event, prompt=queued_prompt, turn_id="replay-turn")
        with (
            patch.object(AUTO, "AppServerReader") as reader,
            patch.object(
                AUTO,
                "session_input",
                return_value={
                    "task": queued_prompt,
                    "active_profile": {
                        "model": "gpt-6-sol",
                        "effort": "medium",
                        "speed": None,
                    },
                },
            ),
        ):
            reader.return_value.__enter__.return_value.call.return_value = {
                "data": [],
                "nextCursor": None,
            }
            result = AUTO.prepare(replay_event)
        self.assertIn("Игнорируй", result["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(STATE.read_state(path)["phase"], "queued")
        self.assertEqual(STATE.read_state(path)["replay_turn_id"], "replay-turn")

    def test_dequeued_request_on_old_profile_is_blocked(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        queued_prompt = INPUT.replay_prompt(self.prompt, "nonce")
        state.update(
            phase="queued",
            queued_submission_id="queued-1",
            queued_at=100,
            queued_prompt_digest=INPUT.prompt_digest(queued_prompt),
        )
        STATE.write_state(path, state)
        replay_event = dict(self.event, prompt=queued_prompt, turn_id="replay-turn")
        with (
            patch.object(AUTO, "AppServerReader") as reader,
            patch.object(
                AUTO,
                "session_input",
                return_value={
                    "task": self.prompt,
                    "active_profile": self.active,
                },
            ),
        ):
            reader.return_value.__enter__.return_value.call.return_value = {
                "data": [],
                "nextCursor": None,
            }
            self.assertEqual(AUTO.prepare(replay_event)["decision"], "block")
        self.assertEqual(STATE.read_state(path)["phase"], "queued")

    def test_same_text_after_dequeue_does_not_admit_manual_resubmission(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        state.update(
            phase="queued",
            queued_submission_id="queued-1",
            queued_at=100,
            replay_turn_id="replay-turn",
            queued_prompt_digest=INPUT.prompt_digest(
                INPUT.replay_prompt(self.prompt, "nonce")
            ),
        )
        STATE.write_state(path, state)
        with patch.object(AUTO, "AppServerReader") as reader:
            reader.return_value.__enter__.return_value.call.side_effect = [
                {"data": [], "nextCursor": None},
                {
                    "data": [
                        {
                            "id": "replay-turn",
                            "startedAt": 101,
                            "status": "inProgress",
                            "completedAt": None,
                        }
                    ],
                    "nextCursor": None,
                },
            ]
            self.assertEqual(
                AUTO.prepare(dict(self.event, turn_id="manual-turn"))["decision"],
                "block",
            )
        self.assertEqual(STATE.read_state(path)["phase"], "queued")

    def test_terminal_replay_releases_new_request_without_completion_timestamp(self):
        for status in ("interrupted", "failed"):
            with self.subTest(status=status):
                path = self.stage()
                state = STATE.read_state(path)
                state.pop("prompt")
                state.update(
                    phase="queued",
                    queued_submission_id="queued-1",
                    queued_at=100,
                    replay_turn_id="replay-turn",
                    queued_prompt_digest=INPUT.prompt_digest(
                        INPUT.replay_prompt(self.prompt, "nonce")
                    ),
                )
                STATE.write_state(path, state)
                new_event = dict(self.event, prompt="Покажи бэклог", turn_id="new-turn")
                with (
                    patch.object(
                        AUTO,
                        "session_input",
                        return_value={
                            "task": "Покажи бэклог",
                            "active_profile": self.active,
                        },
                    ),
                    patch.object(AUTO, "triage", return_value={"decision": "keep"}),
                    patch.object(AUTO, "AppServerReader") as reader,
                ):
                    app = reader.return_value.__enter__.return_value
                    app.call.side_effect = [
                        {"data": [], "nextCursor": None},
                        {
                            "data": [
                                {
                                    "id": "replay-turn",
                                    "startedAt": 101,
                                    "status": status,
                                    "completedAt": None,
                                }
                            ],
                            "nextCursor": None,
                        },
                    ]
                    self.assertIsNone(AUTO.prepare(new_event))
                self.assertEqual(STATE.read_state(path)["phase"], "passed")

    def test_steer_within_replay_turn_preserves_handoff_and_runs_without_retriage(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        state.update(
            phase="queued",
            queued_submission_id="queued-1",
            queued_at=100,
            replay_turn_id="replay-turn",
            queued_prompt_digest=INPUT.prompt_digest(
                INPUT.replay_prompt(self.prompt, "nonce")
            ),
        )
        STATE.write_state(path, state)
        event = dict(self.event, prompt="Покажи бэклог", turn_id="replay-turn")
        with (
            patch.object(AUTO, "AppServerReader") as reader,
            patch.object(AUTO, "triage") as triage,
        ):
            self.assertIsNone(AUTO.prepare(event))
            reader.assert_not_called()
            triage.assert_not_called()
        self.assertEqual(STATE.read_state(path)["replay_turn_id"], "replay-turn")

    def test_replay_context_is_audited_as_replay_not_new_handoff(self):
        event = dict(self.event, turn_id="replay-turn")
        output = io.StringIO()
        with (
            patch.dict(os.environ, {AUTO.AUTO_THREAD_ENV: self.thread_id}),
            patch("sys.stdin", io.StringIO(json.dumps(event))),
            patch.object(sys, "argv", ["hook.py"]),
            patch.object(
                AUTO,
                "prepare",
                return_value={
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": AUTO.REPLAY_CONTEXT,
                    }
                },
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(AUTO.main(), 0)
        self.assertEqual(
            json.loads(output.getvalue())["hookSpecificOutput"]["additionalContext"],
            AUTO.REPLAY_CONTEXT,
        )
        audit = (
            (Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        self.assertEqual(
            [json.loads(line)["outcome"] for line in audit],
            ["auto_started", "auto_replay"],
        )
