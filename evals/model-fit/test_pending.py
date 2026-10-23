"""Model Fit hook regression checks."""

from unittest.mock import patch

from hook_case import AUTO, INPUT, STATE, AutoSwitchCase
from model_fit import queue as QUEUE


class PendingLifecycleTests(AutoSwitchCase):
    def test_new_request_cancels_old_queued_request(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
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
                {"data": [{"id": "queued-1"}], "nextCursor": None},
                {"deleted": True},
            ]
            self.assertIsNone(AUTO.prepare(new_event))
            self.assertEqual(app.call.call_args_list[1].args[0], "thread/queue/delete")
        self.assertEqual(STATE.read_state(path)["phase"], "passed")

    def test_new_request_waits_after_old_item_leaves_queue(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        state.update(
            phase="queued",
            queued_submission_id="queued-1",
            queued_at=100,
            replay_turn_id="replay-turn",
        )
        STATE.write_state(path, state)
        new_event = dict(self.event, prompt="Покажи бэклог", turn_id="new-turn")
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
            self.assertEqual(AUTO.prepare(new_event)["decision"], "block")
        self.assertEqual(STATE.read_state(path)["phase"], "queued")

    def test_completed_replay_releases_new_request(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
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
                            "completedAt": 102,
                            "status": "completed",
                        }
                    ],
                    "nextCursor": None,
                },
                {
                    "data": [
                        {
                            "item": {
                                "type": "userMessage",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": INPUT.replay_prompt(
                                            self.prompt, "nonce"
                                        ),
                                    }
                                ],
                            }
                        }
                    ],
                    "nextCursor": None,
                },
            ]
            state["queued_prompt_digest"] = INPUT.prompt_digest(
                INPUT.replay_prompt(self.prompt, "nonce")
            )
            STATE.write_state(path, state)
            self.assertIsNone(AUTO.prepare(new_event))
            self.assertEqual(
                [call.args[0] for call in app.call.call_args_list],
                [
                    "thread/queue/list",
                    "thread/turns/list",
                    "thread/items/list",
                ],
            )
        self.assertEqual(STATE.read_state(path)["phase"], "passed")

    def test_old_identical_prompt_does_not_confirm_replay(self):
        state = {
            "source_turn_id": self.turn_id,
            "queued_at": 100,
            "queued_prompt_digest": INPUT.prompt_digest(
                INPUT.replay_prompt(self.prompt, "nonce")
            ),
        }
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.return_value = {
                "data": [
                    {
                        "id": "old-turn",
                        "startedAt": 99,
                        "completedAt": 99,
                        "status": "completed",
                    }
                ],
                "nextCursor": None,
            }
            self.assertFalse(QUEUE.replay_finished(app, self.thread_id, state))
            self.assertEqual(app.call.call_count, 1)

    def test_queue_scan_stops_after_bounded_pages(self):
        with patch.object(AUTO, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"data": [], "nextCursor": f"cursor-{index}"}
                for index in range(QUEUE.MAX_QUEUE_PAGES)
            ]
            with self.assertRaisesRegex(ValueError, "bounded"):
                QUEUE.queued_ids(app, self.thread_id)
            self.assertEqual(app.call.call_count, QUEUE.MAX_QUEUE_PAGES)

    def test_legacy_pending_state_accepts_new_turn_without_comparing_text(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
        STATE.write_state(path, state)
        with (
            patch.object(
                AUTO,
                "session_input",
                return_value={"task": self.prompt, "active_profile": self.active},
            ),
            patch.object(AUTO, "triage", return_value={"decision": "keep"}),
            patch.object(AUTO, "AppServerReader") as reader,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                {"data": [{"id": "queued-1"}], "nextCursor": None},
                {"deleted": True},
            ]
            self.assertIsNone(AUTO.prepare(dict(self.event, turn_id="new-turn")))
        self.assertEqual(STATE.read_state(path)["phase"], "passed")

    def test_interrupted_source_releases_stranded_same_request(self):
        path = self.stage()
        state = STATE.read_state(path)
        state.pop("prompt")
        state.update(phase="queued", queued_submission_id="queued-1", queued_at=100)
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
                {"data": [{"id": "queued-1"}], "nextCursor": None},
                {"deleted": True},
            ]
            self.assertIsNone(AUTO.prepare(new_event))
            self.assertEqual(
                [call.args[0] for call in app.call.call_args_list],
                [
                    "thread/queue/list",
                    "thread/queue/delete",
                ],
            )
        self.assertEqual(STATE.read_state(path)["phase"], "passed")
