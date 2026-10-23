"""Model Fit hook regression checks."""

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hook_case import AUTO, AutoSwitchCase


class AnswerGuardTests(AutoSwitchCase):
    def test_main_stop_emits_one_continuation_decision(self):
        event = dict(
            self.event,
            hook_event_name="Stop",
            turn_id="replay-turn",
            stop_hook_active=False,
            last_assistant_message="Чужой ответ",
        )
        output = io.StringIO()
        with (
            patch.dict(os.environ, {AUTO.AUTO_THREAD_ENV: self.thread_id}),
            patch("sys.stdin", io.StringIO(json.dumps(event))),
            patch.object(sys, "argv", ["hook.py"]),
            patch.object(
                AUTO,
                "guard_replay_answer",
                return_value={
                    "decision": "block",
                    "reason": AUTO.REPLAY_STOP_REASON,
                },
            ) as guard,
            redirect_stdout(output),
        ):
            self.assertEqual(AUTO.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["decision"], "block")
        guard.assert_called_once_with(event)

    def test_queue_error_records_location_without_error_payload(self):
        error_output = io.StringIO()
        with (
            patch(
                "sys.argv",
                [
                    "hook.py",
                    "queue",
                    "--thread-id",
                    self.thread_id,
                    "--turn-id",
                    self.turn_id,
                ],
            ),
            patch.object(
                AUTO, "enqueue", side_effect=RuntimeError("private request text")
            ),
            redirect_stderr(error_output),
        ):
            self.assertEqual(AUTO.main(), 1)
        audit = (
            Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl"
        ).read_text()
        failure = json.loads(audit.splitlines()[-1])
        self.assertEqual(failure["outcome"], "auto_queue_error:RuntimeError")
        self.assertEqual(failure["details"]["hook_event"], "queue")
        self.assertIn("failure_line", failure["details"])
        self.assertNotIn("private request text", audit + error_output.getvalue())

    def test_malformed_hook_event_is_audited_without_payload(self):
        output = io.StringIO()
        with (
            patch.dict(os.environ, {AUTO.AUTO_THREAD_ENV: self.thread_id}),
            patch("sys.argv", ["hook.py"]),
            patch("sys.stdin", io.StringIO('["private request text"]')),
            redirect_stdout(output),
        ):
            self.assertEqual(AUTO.main(), 0)
        self.assertEqual(output.getvalue(), "")
        audit = (
            Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl"
        ).read_text()
        self.assertEqual(json.loads(audit)["outcome"], "auto_error:ValueError")
        self.assertNotIn("private request text", audit)

    def test_stop_retries_only_unrelated_replay_answer(self):
        content, queued = self.stage_replay()
        event = dict(
            self.event,
            hook_event_name="Stop",
            turn_id="replay-turn",
            stop_hook_active=False,
            last_assistant_message="Готово: закрыты старые #138 и #126",
        )
        with (
            patch.object(AUTO, "AppServerReader") as reader,
            patch("answer.classify_answer", return_value="unrelated") as classify,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                self.source_response(content),
                {
                    "data": [{"item": {"type": "userMessage", "content": queued}}],
                    "nextCursor": None,
                },
            ]
            result = AUTO.guard_replay_answer(event)
        self.assertEqual(
            result, {"decision": "block", "reason": AUTO.REPLAY_STOP_REASON}
        )
        classify.assert_called_once_with(
            self.prompt,
            self.recommendation["task_inference"],
            event["last_assistant_message"],
        )
        event["stop_hook_active"] = True
        with patch.object(AUTO, "AppServerReader") as reader:
            self.assertIsNone(AUTO.guard_replay_answer(event))
            reader.assert_not_called()

    def test_stop_accepts_relevant_replay_answer(self):
        content, queued = self.stage_replay()
        event = dict(
            self.event,
            hook_event_name="Stop",
            turn_id="replay-turn",
            stop_hook_active=False,
            last_assistant_message="Проверил backend #124; нужен доступ к Reg.ru",
        )
        with (
            patch.object(AUTO, "AppServerReader") as reader,
            patch("answer.classify_answer", return_value="relevant") as classify,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                self.source_response(content),
                {
                    "data": [{"item": {"type": "userMessage", "content": queued}}],
                    "nextCursor": None,
                },
            ]
            self.assertIsNone(AUTO.guard_replay_answer(event))
        classify.assert_called_once()

    def test_stop_skips_multimodal_or_steered_replay(self):
        content = [
            {"type": "text", "text": self.prompt},
            {"type": "localImage", "path": "/tmp/reference.png"},
        ]
        original, queued = self.stage_replay(content)
        event = dict(
            self.event,
            hook_event_name="Stop",
            turn_id="replay-turn",
            stop_hook_active=False,
            last_assistant_message="Ответ по картинке",
        )
        with (
            patch.object(AUTO, "AppServerReader") as reader,
            patch("answer.classify_answer") as classify,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                self.source_response(original),
                {
                    "data": [{"item": {"type": "userMessage", "content": queued}}],
                    "nextCursor": None,
                },
            ]
            self.assertIsNone(AUTO.guard_replay_answer(event))
            classify.assert_not_called()
        with (
            patch.object(AUTO, "AppServerReader") as reader,
            patch("answer.classify_answer") as classify,
        ):
            reader.return_value.__enter__.return_value.call.side_effect = [
                self.source_response(original),
                {
                    "data": [
                        {"item": {"type": "userMessage", "content": queued}},
                        {
                            "item": {
                                "type": "userMessage",
                                "content": [{"type": "text", "text": "Уточнение"}],
                            }
                        },
                    ],
                    "nextCursor": None,
                },
            ]
            self.assertIsNone(AUTO.guard_replay_answer(event))
            classify.assert_not_called()

    def test_stop_evaluator_failure_does_not_block_turn(self):
        event = dict(
            self.event,
            hook_event_name="Stop",
            turn_id="replay-turn",
            stop_hook_active=False,
            last_assistant_message="Ответ",
        )
        output = io.StringIO()
        with (
            patch.dict(os.environ, {AUTO.AUTO_THREAD_ENV: self.thread_id}),
            patch("sys.stdin", io.StringIO(json.dumps(event))),
            patch.object(sys, "argv", ["hook.py"]),
            patch.object(
                AUTO, "guard_replay_answer", side_effect=RuntimeError("unavailable")
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(AUTO.main(), 0)
        self.assertEqual(output.getvalue(), "")
        audit = (
            (Path(self.temporary.name) / ".tmp/model-fit-hook-audit/test-thread.jsonl")
            .read_text()
            .splitlines()
        )
        self.assertEqual(json.loads(audit[-1])["outcome"], "auto_error:RuntimeError")
