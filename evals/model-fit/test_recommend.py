"""Tests for the opt-in Desktop Model Fit hook."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "plugins/model-fit/skills/model-fit/scripts/recommend.py"
sys.path.insert(0, str(MODULE_PATH.parent))
from model_fit import audit as AUDIT, recommendation as RECOMMENDATION

SPEC = importlib.util.spec_from_file_location("recommend", MODULE_PATH)
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


class RecommendationHookTests(unittest.TestCase):
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
                status = HOOK.main()
        return status, output.getvalue(), read, triage

    def test_other_thread_does_not_run_preflight(self):
        event = dict(self.event, session_id="other-thread")
        status, output, read, triage = self.run_hook(event)
        self.assertEqual(status, 0)
        self.assertEqual(output, "")
        read.assert_not_called()
        triage.assert_not_called()

    def test_summary_history_preserves_user_context_without_tool_output(self):
        with patch.object(RECOMMENDATION, "AppServerReader") as reader:
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
            request = HOOK.session_input(self.event)
        self.assertIn("Предыдущая задача", request["context"])
        self.assertNotIn("large tool output", request["context"])
        self.assertEqual(app.call.call_args_list[1].args[1]["itemsView"], "summary")

    def test_summary_history_omits_current_prompt_with_trailing_newline(self):
        event = dict(self.event, prompt="Покажи бэклог\n")
        with patch.object(RECOMMENDATION, "AppServerReader") as reader:
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
            request = HOOK.session_input(event)
        self.assertEqual(
            request["context"],
            "Предыдущие запросы пользователя как контекст:\nПредыдущая задача",
        )

    def test_attachment_only_prompt_does_not_require_resubmission(self):
        with patch.object(RECOMMENDATION, "AppServerReader") as reader:
            app = reader.return_value.__enter__.return_value
            app.call.side_effect = [
                {"thread": {"model": "gpt-6-luna", "reasoningEffort": "low"}},
                {"data": []},
            ]
            request = HOOK.session_input(dict(self.event, prompt=""))
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
                self.assertEqual(HOOK.main(), 0)
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
                status = HOOK.main()
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
                patch.object(HOOK, "save_pending", side_effect=OSError("disk full")),
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
