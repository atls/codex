"""Desktop native history scenarios."""

import copy

from unittest.mock import MagicMock, patch

from vector_prime.application.handoff.types.progress import TransferInputEvidence
from vector_prime.application.handoff.types.replay import BoundReplay, UnboundReplay
from vector_prime.entrypoints.hooks import operations
import vector_prime.application.submission.helpers.content as HANDOFF_INPUT
import vector_prime.infrastructure.adapters.codex.history as HANDOFF_CODEX
import vector_prime.infrastructure.adapters.codex.transport.connection as CODEX_CONNECTION


from fixtures.autoswitch.desktop import DesktopHandoffCase


class NativeHistoryTests(DesktopHandoffCase):
    def test_source_input_follows_native_pagination(self):
        source = [{"type": "text", "text": self.prompt}]
        steering = [{"type": "image", "url": "data:image/png;base64,aW1hZ2U="}]
        for source_page in (0, 6):
            with self.subTest(source_page=source_page):
                app = MagicMock()
                pages = [
                    {
                        "data": [{"item": {"type": "agentMessage"}}] * 100,
                        "nextCursor": f"page-{index + 1}",
                    }
                    for index in range(7)
                ]
                pages[source_page]["data"][0] = {
                    "item": {"type": "userMessage", "content": source}
                }
                pages.append(self.source_response(steering))
                app.call.side_effect = pages
                self.assertEqual(
                    HANDOFF_CODEX.source_input(
                        app, self.thread_id, self.turn_id, include_steering=True
                    ),
                    source + steering,
                )

    def test_source_input_rejects_repeated_native_cursor(self):
        app = MagicMock()
        app.call.side_effect = [
            {"data": [], "nextCursor": "repeated"},
            {"data": [], "nextCursor": "repeated"},
        ]
        with self.assertRaisesRegex(ValueError, "pagination repeated a cursor"):
            HANDOFF_CODEX.source_input(
                app, self.thread_id, self.turn_id, include_steering=True
            )

    def test_source_input_timeout_never_returns_partial_input(self):
        app = MagicMock()
        app.call.return_value = {
            **self.source_response([{"type": "text", "text": self.prompt}]),
            "nextCursor": "next",
        }
        with patch.object(HANDOFF_CODEX.time, "monotonic", side_effect=[0, 0, 51]):
            with self.assertRaises(TimeoutError):
                HANDOFF_CODEX.source_input(
                    app, self.thread_id, self.turn_id, include_steering=True
                )

    def test_terminal_turn_with_lost_attachment_does_not_confirm_replay(self):
        queued = copy.deepcopy(
            [
                {"type": "text", "text": self.prompt},
                {"type": "image", "url": "same-image"},
            ]
        )
        replay = UnboundReplay(
            self.turn_id,
            100,
            TransferInputEvidence("native_input", HANDOFF_INPUT.input_digest(queued)),
        )
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {
                    "data": [
                        {"id": "replay-turn", "startedAt": 101, "status": "completed"}
                    ]
                },
                self.source_response([queued[0]]),
            ]
            self.assertFalse(HANDOFF_CODEX.replay_finished(app, self.thread_id, replay))

    def test_json_rpc_rejection_has_distinct_exception(self):
        reader = object.__new__(HANDOFF_CODEX.AppServerReader)
        reader.next_id = 0
        with (
            patch.object(reader, "send"),
            patch.object(
                reader,
                "read",
                return_value={
                    "id": 0,
                    "error": {"code": -32000, "message": "queue full"},
                },
            ),
        ):
            with self.assertRaisesRegex(
                CODEX_CONNECTION.AppServerRPCError, "queue full"
            ):
                reader.call("thread/queue/add", {}, 1)

    def test_terminal_replay_beyond_first_page_releases_guard(self):
        replay = BoundReplay("replay-turn")
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {
                    "data": [
                        {"id": f"blocked-{i}", "startedAt": 103, "status": "completed"}
                        for i in range(5)
                    ],
                    "nextCursor": "older",
                },
                {
                    "data": [
                        {"id": "replay-turn", "startedAt": 101, "status": "failed"}
                    ],
                    "nextCursor": None,
                },
            ]
            self.assertTrue(HANDOFF_CODEX.replay_finished(app, self.thread_id, replay))
            self.assertEqual(app.call.call_args_list[1].args[1]["cursor"], "older")

    def test_bound_replay_started_before_queue_receipt_is_still_terminal(self):
        replay = BoundReplay("replay-turn")
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.return_value = {
                "data": [
                    {"id": "replay-turn", "startedAt": 101, "status": "completed"}
                ],
                "nextCursor": None,
            }
            self.assertTrue(HANDOFF_CODEX.replay_finished(app, self.thread_id, replay))

    def test_unbound_running_turn_or_missing_source_cannot_release_guard(self):
        for turns in [
            [
                {"id": "unbound", "status": "inProgress"},
                {"id": self.turn_id, "status": "completed"},
            ],
            [{"id": "other", "status": "completed"}],
            [{"id": self.turn_id, "status": "inProgress"}],
        ]:
            with (
                self.subTest(turns=turns),
                patch.object(operations, "AppServerReader") as reader,
            ):
                app = reader.return_value.__enter__.return_value
                app.call.return_value = {"data": turns, "nextCursor": None}
                self.assertFalse(
                    HANDOFF_CODEX.source_terminal_without_replay(
                        app, self.thread_id, self.turn_id, "new-turn"
                    )
                )

    def test_handoff_history_repeated_cursor_retains_unknown_outcome(self):
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.return_value = {"data": [], "nextCursor": "repeated"}
            with self.assertRaisesRegex(ValueError, "cursor repeated"):
                HANDOFF_CODEX.source_terminal_without_replay(
                    app, self.thread_id, self.turn_id, "new-turn"
                )

    def test_old_identical_prompt_does_not_confirm_replay(self):
        replay = UnboundReplay(
            self.turn_id,
            100,
            TransferInputEvidence(
                "legacy_prompt", HANDOFF_INPUT.prompt_digest(self.prompt)
            ),
        )
        with patch.object(operations, "AppServerReader") as reader:
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
            self.assertFalse(HANDOFF_CODEX.replay_finished(app, self.thread_id, replay))
            self.assertEqual(app.call.call_count, 1)

    def test_queue_scan_stops_after_bounded_pages(self):
        with patch.object(operations, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"data": [], "nextCursor": f"cursor-{index}"}
                for index in range(HANDOFF_CODEX.MAX_QUEUE_PAGES)
            ]
            with self.assertRaisesRegex(ValueError, "bounded"):
                HANDOFF_CODEX.queued_ids(app, self.thread_id)
            self.assertEqual(app.call.call_count, HANDOFF_CODEX.MAX_QUEUE_PAGES)
