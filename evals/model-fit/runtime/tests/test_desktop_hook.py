"""Tests for the opt-in Desktop Model Fit hook."""

import sys
from pathlib import Path

sys.path.insert(
    0, str((Path(__file__).resolve().parents[4] / "plugins/model-fit") / "src")
)

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
import model_fit.infrastructure.codex.conversation.queries as RUNTIME
from model_fit.entrypoints.desktop import prompt as HOOK
from model_fit.infrastructure.audit import writer as AUDIT


class DesktopHookTests(unittest.TestCase):
    active = {"model": "gpt-6-luna", "effort": "low", "speed": None}
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "test-thread",
        "cwd": "/tmp",
        "model": "gpt-6-luna",
        "prompt": "Спроектируй поисковик по снимкам",
    }

    def run_hook(self, event, decision=None):
        output = io.StringIO()
        request = {"task": event["prompt"], "active_profile": self.active}
        with tempfile.TemporaryDirectory() as home:
            with (
                patch.dict(
                    os.environ,
                    {HOOK.PILOT_THREAD_ENV: "test-thread", "CODEX_HOME": home},
                ),
                patch("sys.stdin", io.StringIO(json.dumps(event, ensure_ascii=False))),
                patch.object(HOOK, "session_input", return_value=request) as read,
                patch.object(HOOK, "triage", return_value=decision) as triage,
                redirect_stdout(output),
            ):
                status = HOOK.handle_prompt()
        return status, output.getvalue(), read, triage

    def test_other_thread_does_not_run_preflight(self):
        event = dict(self.event, session_id="other-thread")
        status, output, read, triage = self.run_hook(event)
        self.assertEqual(status, 0)
        self.assertEqual(output, "")
        read.assert_not_called()
        triage.assert_not_called()

    def test_summary_history_preserves_user_context_without_tool_output(self):
        with patch.object(RUNTIME, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}},
                {
                    "data": [
                        {
                            "items": [
                                {
                                    "type": "userMessage",
                                    "content": [
                                        {"type": "text", "text": "Предыдущая задача"}
                                    ],
                                },
                                {
                                    "type": "commandExecution",
                                    "aggregatedOutput": "large tool output",
                                },
                            ]
                        }
                    ]
                },
            ]
            request = RUNTIME.session_input(self.event)
        self.assertIn("Предыдущая задача", request["context"])
        self.assertNotIn("large tool output", request["context"])
        self.assertEqual(app.call.call_args_list[1].args[1]["itemsView"], "summary")

    def test_child_context_is_read_from_the_child_thread(self):
        event = {**self.event, "agent_id": "child-thread"}
        with patch.object(RUNTIME, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}},
                {"data": []},
            ]
            request = RUNTIME.session_input(event)
        self.assertEqual(request["active_profile"], self.active)
        self.assertTrue(
            all(
                call.args[1]["threadId"] == "child-thread"
                for call in app.call.call_args_list
            )
        )

    def test_summary_history_omits_current_prompt_with_trailing_newline(self):
        event = dict(self.event, prompt="Покажи бэклог\n")
        with patch.object(RUNTIME, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}},
                {
                    "data": [
                        {
                            "items": [
                                {
                                    "type": "userMessage",
                                    "content": [
                                        {"type": "text", "text": "Покажи бэклог\n"}
                                    ],
                                },
                                {
                                    "type": "userMessage",
                                    "content": [
                                        {"type": "text", "text": "Предыдущая задача"}
                                    ],
                                },
                            ]
                        }
                    ]
                },
            ]
            request = RUNTIME.session_input(event)
        self.assertIn("Пользователь: Предыдущая задача", request["context"])
        self.assertNotIn("Покажи бэклог", request["context"])

    def test_continuation_includes_plan_and_excludes_tools_and_current_turn(self):
        event = dict(self.event, prompt="ну так вперёд", turn_id="current")
        with patch.object(RUNTIME, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}},
                {
                    "data": [
                        {
                            "id": "current",
                            "items": [
                                {"type": "agentMessage", "text": "FUTURE ANSWER"}
                            ],
                        },
                        {
                            "id": "previous",
                            "items": [
                                {
                                    "type": "userMessage",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "Подготовь план восстановления",
                                        }
                                    ],
                                },
                                {
                                    "type": "agentMessage",
                                    "phase": "final_answer",
                                    "text": "Проверить действующий reverse proxy, восстановить внешний маршрут и проверить rollback.",
                                },
                                {"type": "reasoning", "text": "HIDDEN REASONING"},
                                {
                                    "type": "commandExecution",
                                    "aggregatedOutput": "TOOL OUTPUT",
                                },
                            ],
                        },
                    ]
                },
            ]
            request = RUNTIME.session_input(event)
        self.assertIn("rollback", request["context"])
        self.assertIn("Подготовь план восстановления", request["context"])
        for excluded in ["FUTURE ANSWER", "HIDDEN REASONING", "TOOL OUTPUT"]:
            self.assertNotIn(excluded, request["context"])
        self.assertNotIn("prior_choice", request)

    def test_context_limit_keeps_nearest_plan_when_older_messages_are_large(self):
        with patch.object(RUNTIME, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}},
                {
                    "data": [
                        {
                            "items": [
                                {
                                    "type": "userMessage",
                                    "content": [{"type": "text", "text": "a" * 6000}],
                                },
                                {
                                    "type": "agentMessage",
                                    "phase": "final_answer",
                                    "text": "NEAREST PLAN" if n == 0 else "b" * 6000,
                                },
                            ]
                        }
                        for n in range(3)
                    ]
                },
            ]
            request = RUNTIME.session_input(self.event)
        self.assertIn("NEAREST PLAN", request["context"])
        self.assertLessEqual(len(request["context"]), 20000)

    def test_paginated_context_keeps_choice_and_failure_behind_control_turns(self):
        event = dict(self.event, prompt="пабли", turn_id="current")
        control = {
            "items": [
                {
                    "type": "userMessage",
                    "content": [
                        {
                            "type": "text",
                            "text": "Model Fit: заверши технический перенос запроса",
                        }
                    ],
                },
                {"type": "agentMessage", "text": "TECHNICAL ONLY"},
            ]
        }
        with patch.object(RUNTIME, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}},
                {"data": [control] * 5, "nextCursor": "earlier"},
                {
                    "data": [
                        {
                            "id": "choice",
                            "items": [
                                {
                                    "type": "userMessage",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "Сохрани выбранный мной профиль для этой работы",
                                        }
                                    ],
                                },
                                {
                                    "type": "agentMessage",
                                    "phase": "final_answer",
                                    "text": "Публикацию не выполнил",
                                },
                            ],
                        }
                    ],
                    "nextCursor": None,
                },
            ]
            request = RUNTIME.session_input(event)
        self.assertIn("Сохрани выбранный мной профиль", request["context"])
        self.assertIn("Публикацию не выполнил", request["context"])
        self.assertNotIn("TECHNICAL ONLY", request["context"])
        self.assertEqual(app.call.call_args_list[-1].args[1]["cursor"], "earlier")

    def test_attachment_only_prompt_does_not_require_resubmission(self):
        with patch.object(RUNTIME, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}},
                {"data": []},
            ]
            request = RUNTIME.session_input(dict(self.event, prompt=""))
        self.assertTrue(request["task"])
        self.assertEqual(request["active_profile"], self.active)

    def test_audit_records_target_hook_without_prompt_text(self):
        event = dict(self.event, turn_id="turn-123")
        with tempfile.TemporaryDirectory() as home:
            with (
                patch.dict(
                    os.environ,
                    {HOOK.PILOT_THREAD_ENV: "test-thread", "CODEX_HOME": home},
                ),
                patch("sys.stdin", io.StringIO(json.dumps(event, ensure_ascii=False))),
                patch.object(
                    HOOK,
                    "session_input",
                    return_value={
                        "task": event["prompt"],
                        "active_profile": self.active,
                    },
                ),
                patch.object(HOOK, "triage", return_value={"decision": "keep"}),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(HOOK.handle_prompt(), 0)
                audit_text = AUDIT.audit_path("test-thread").read_text()
            entries = [json.loads(line) for line in audit_text.splitlines()]
        self.assertEqual([entry["outcome"] for entry in entries], ["started", "keep"])
        self.assertEqual(
            [entry["turn_id"] for entry in entries], ["turn-123", "turn-123"]
        )
        self.assertNotIn(event["prompt"], audit_text)

    def test_audit_uses_fixed_diagnostic_fields_and_reports_write_failure(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.dict(os.environ, {"CODEX_HOME": home}):
                self.assertTrue(
                    AUDIT.record_audit(
                        "test-thread",
                        "test-turn",
                        "auto_guard_block",
                        {
                            "hook_event": "PreToolUse",
                            "reason_code": "state_lock_busy",
                            "prompt": "private request text",
                        },
                    )
                )
                audit_text = AUDIT.audit_path("test-thread").read_text()
        entry = json.loads(audit_text)
        self.assertEqual(
            entry["details"],
            {
                "hook_event": "PreToolUse",
                "reason_code": "state_lock_busy",
            },
        )
        self.assertNotIn("private request text", audit_text)
        error_output = io.StringIO()
        with (
            patch.object(AUDIT, "append_audit", side_effect=OSError("private path")),
            redirect_stderr(error_output),
        ):
            self.assertFalse(
                AUDIT.record_audit("test-thread", "test-turn", "auto_guard_block")
            )
        self.assertIn("audit write failed (OSError)", error_output.getvalue())
        self.assertNotIn("private path", error_output.getvalue())

    def test_audit_records_triage_recommendation(self):
        request = {"task": self.event["prompt"], "active_profile": self.active}
        decision = {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "medium",
            "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
            "official_guidance": "OpenAI рекомендует выбирать модель по задаче.",
            "task_inference": "Для этой задачи нужен другой профиль.",
            "reason": "Нужна более глубокая техническая работа.",
        }
        outcomes = []
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(HOOK, "triage", return_value=decision):
                output = HOOK.decide(
                    request, Path(temporary) / "pending.json", outcomes.append
                )
        self.assertEqual(output["decision"], "block")
        self.assertEqual(outcomes, ["recommend_stronger"])

    def test_matching_profile_passes_silently(self):
        decision = {"decision": "keep"}
        status, output, read, triage = self.run_hook(self.event, decision)
        self.assertEqual(status, 0)
        self.assertEqual(output, "")
        read.assert_called_once()
        triage.assert_called_once()

    def test_confirmed_mismatch_blocks_before_model(self):
        decision = {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "medium",
            "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
            "official_guidance": "OpenAI рекомендует выбирать модель по задаче.",
            "task_inference": "Для этой задачи нужен другой профиль.",
            "reason": "Нужна более глубокая техническая работа.",
        }
        status, output, _, _ = self.run_hook(self.event, decision)
        self.assertEqual(status, 0)
        result = json.loads(output)
        self.assertEqual(result["decision"], "block")
        self.assertIn("gpt-6.1-sol / medium", result["reason"])
        self.assertIn("повтори этот запрос", result["reason"])
        self.assertIn(
            "Рекомендация OpenAI: OpenAI рекомендует выбирать модель по задаче.",
            result["reason"],
        )
        self.assertIn(
            "Вывод для этой задачи: Для этой задачи нужен другой профиль.",
            result["reason"],
        )

    def test_unknown_does_not_claim_profile_is_suitable(self):
        status, output, _, _ = self.run_hook(self.event, {"decision": "unknown"})
        self.assertEqual(status, 0)
        self.assertEqual(set(json.loads(output)), {"systemMessage"})

    def test_reader_failure_does_not_block_user_turn(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as home:
            with (
                patch.dict(
                    os.environ,
                    {HOOK.PILOT_THREAD_ENV: "test-thread", "CODEX_HOME": home},
                ),
                patch(
                    "sys.stdin", io.StringIO(json.dumps(self.event, ensure_ascii=False))
                ),
                patch.object(
                    HOOK, "session_input", side_effect=RuntimeError("unavailable")
                ),
                patch.object(HOOK, "triage") as triage,
                redirect_stdout(output),
            ):
                status = HOOK.handle_prompt()
        self.assertEqual(status, 0)
        self.assertIn(
            "профиль не оценён", json.loads(output.getvalue())["systemMessage"]
        )
        triage.assert_not_called()

    def test_pending_mismatch_blocks_retry_without_another_model_call(self):
        request = {"task": self.event["prompt"], "active_profile": self.active}
        decision = {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "medium",
            "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
            "official_guidance": "OpenAI рекомендует выбирать модель по задаче.",
            "task_inference": "Для этой задачи нужен другой профиль.",
            "reason": "Задача требует более сильного профиля.",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pending.json"
            with patch.object(HOOK, "triage", return_value=decision) as triage:
                first = HOOK.decide(request, path)
                second = HOOK.decide(request, path)
            self.assertEqual(first, second)
            self.assertEqual(first["decision"], "block")
            triage.assert_called_once()

    def test_selected_recommended_profile_releases_same_request(self):
        request = {"task": self.event["prompt"], "active_profile": self.active}
        decision = {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "medium",
            "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
            "official_guidance": "OpenAI рекомендует выбирать модель по задаче.",
            "task_inference": "Для этой задачи нужен другой профиль.",
            "reason": "Задача требует более сильного профиля.",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pending.json"
            with patch.object(HOOK, "triage", return_value=decision) as triage:
                self.assertEqual(HOOK.decide(request, path)["decision"], "block")
                selected = {
                    "task": request["task"],
                    "active_profile": {
                        "model": "gpt-6.1-sol",
                        "effort": "medium",
                        "speed": None,
                    },
                }
                self.assertIsNone(HOOK.decide(selected, path))
            self.assertFalse(path.exists())
            triage.assert_called_once()

    def test_state_write_failure_still_blocks_confirmed_mismatch(self):
        request = {"task": self.event["prompt"], "active_profile": self.active}
        decision = {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "medium",
            "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
            "official_guidance": "OpenAI рекомендует выбирать модель по задаче.",
            "task_inference": "Для этой задачи нужен другой профиль.",
            "reason": "Задача требует более сильного профиля.",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pending.json"
            outcomes = []
            with (
                patch.object(HOOK, "triage", return_value=decision),
                patch(
                    "model_fit.infrastructure.handoff.recommendations.files.save_pending",
                    side_effect=OSError("disk full"),
                ),
            ):
                output = HOOK.decide(request, path, outcomes.append)
            self.assertEqual(output["decision"], "block")
            self.assertIn("не сохранилось", output["reason"])
            self.assertEqual(outcomes, ["recommend_stronger", "pending_save_error"])

    def test_new_task_does_not_inherit_old_recommendation(self):
        request = {"task": self.event["prompt"], "active_profile": self.active}
        decision = {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "medium",
            "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
            "official_guidance": "OpenAI рекомендует выбирать модель по задаче.",
            "task_inference": "Для этой задачи нужен другой профиль.",
            "reason": "Задача требует более сильного профиля.",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pending.json"
            with patch.object(HOOK, "triage", return_value=decision):
                self.assertEqual(HOOK.decide(request, path)["decision"], "block")
            next_request = {"task": "Собери темы писем", "active_profile": self.active}
            with patch.object(
                HOOK, "triage", return_value={"decision": "unknown"}
            ) as triage:
                self.assertIn("systemMessage", HOOK.decide(next_request, path))
            triage.assert_called_once_with(next_request)
            self.assertFalse(path.exists())
            selected = {
                "task": request["task"],
                "active_profile": {
                    "model": "gpt-6.1-sol",
                    "effort": "medium",
                    "speed": None,
                },
            }
            with patch.object(
                HOOK, "triage", return_value={"decision": "keep"}
            ) as triage:
                self.assertIsNone(HOOK.decide(selected, path))
            triage.assert_called_once_with(selected)

    def test_failed_invalidation_does_not_leave_stale_bypass_active(self):
        request = {"task": self.event["prompt"], "active_profile": self.active}
        decision = {
            "decision": "recommend_stronger",
            "active_model": "gpt-6-luna",
            "active_effort": "low",
            "recommended_model": "gpt-6.1-sol",
            "recommended_effort": "medium",
            "official_source_url": "https://developers.openai.com/api/docs/guides/model-selection",
            "official_guidance": "OpenAI рекомендует выбирать модель по задаче.",
            "task_inference": "Для этой задачи нужен другой профиль.",
            "reason": "Задача требует более сильного профиля.",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pending.json"
            with patch.object(HOOK, "triage", return_value=decision):
                self.assertEqual(HOOK.decide(request, path)["decision"], "block")
            next_request = {"task": "Новая задача", "active_profile": self.active}
            with (
                patch.object(Path, "unlink", side_effect=OSError("permission denied")),
                patch.object(HOOK, "triage") as triage,
            ):
                output = HOOK.decide(next_request, path)
            self.assertEqual(output["decision"], "block")
            triage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
