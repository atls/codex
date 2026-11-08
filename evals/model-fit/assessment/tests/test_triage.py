"""Regression checks for the Model Fit preflight consumer boundary."""

from __future__ import annotations

import model_fit.infrastructure.adapters.codex.sources as SOURCES

from pathlib import Path


import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
HERE = ROOT / "evals/model-fit"
MODULE_PATH = ROOT / "plugins/model-fit/src/triage.py"
import model_fit.assessment.assess as TRIAGE
import model_fit.entrypoints.cli.assess as CLI
import model_fit.infrastructure.adapters.codex.assessment as ASSESSMENT_CLIENT
from model_fit.assessment.failures.source_unavailable import (
    SourceUnavailable,
)
from model_fit.assessment.validation import empty_decision, validate
from model_fit.infrastructure.adapters.codex.catalog import NativeCatalog


class TriageContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sources = (HERE / "fixtures/preflight-sources-2026-10-16.txt").read_text()
        catalog = json.loads(
            sources.split("<codex_catalog>", 1)[1].split("</codex_catalog>", 1)[0]
        )
        cls.models = NativeCatalog.from_projection(catalog)
        cls.profiles = json.loads((HERE / "fixtures/triage-decisions.json").read_text())

    def saved_output(self, case_id: str) -> tuple[dict, dict]:
        case = next(case for case in self.profiles[0]["cases"] if case["id"] == case_id)
        active = dict(case["active_profile"])
        return active, {
            "active_model": active["model"],
            "active_effort": active["effort"],
            "active_speed": active["speed"],
            "decision": case["decision"],
            "recommended_model": case["target_model"],
            "recommended_effort": case["target_effort"],
            "recommended_speed": case["target_speed"],
            "official_source_url": case["official_source_url"],
            "official_guidance": case["official_guidance"],
            "task_inference": case["task_inference"],
            "reason": case["reason"],
        }

    def test_decision_contract_vectors_remain_consumable(self) -> None:
        for profile in self.profiles:
            for case in profile["cases"]:
                if case["id"] == "ordinary-dialogue":
                    continue
                active = case["active_profile"]
                output = {
                    "active_model": active["model"],
                    "active_effort": active["effort"],
                    "active_speed": active["speed"],
                    "decision": case["decision"],
                    "recommended_model": case["target_model"],
                    "recommended_effort": case["target_effort"],
                    "recommended_speed": case["target_speed"],
                    "official_source_url": case["official_source_url"],
                    "official_guidance": case["official_guidance"],
                    "task_inference": case["task_inference"],
                    "reason": case["reason"],
                }
                with self.subTest(
                    profile=(profile["model"], profile["effort"]), case=case["id"]
                ):
                    result = validate(output, active, self.models)
                    self.assertEqual(result["decision"], case["decision"])

    def test_assessment_sends_original_native_items_to_codex_turn(self):
        from unittest.mock import MagicMock

        active, output = self.saved_output("writer-delegation-only")
        native = [
            {"type": "text", "text": "Сравни вложения", "text_elements": []},
            {"type": "localImage", "path": "/fixture/complex-a.png"},
            {"type": "image", "url": "data:image/png;base64,Yg==", "detail": "high"},
        ]
        app = MagicMock()
        app.__enter__.return_value = app
        app.skill_file = Path("/fixture/SKILL.md")
        app.call.side_effect = [
            {
                "data": [
                    {
                        "skills": [
                            {
                                "name": "model-fit",
                                "enabled": True,
                                "path": str(app.skill_file),
                            }
                        ]
                    }
                ]
            },
            {"thread": {"id": "assessment"}},
            {"turn": {"id": "assessment-turn"}},
        ]
        app.wait_turn.return_value = "completed"
        app.events = [
            {
                "method": "item/completed",
                "params": {
                    "item": {
                        "type": "userMessage",
                        "content": [
                            {
                                "type": "skill",
                                "name": "model-fit",
                                "path": str(app.skill_file),
                            }
                        ],
                    }
                },
            },
            {
                "method": "item/completed",
                "params": {
                    "item": {"type": "agentMessage", "text": json.dumps(output)}
                },
            },
        ]
        result = TRIAGE.assess(
            {"task": "Сравни вложения", "input": native, "active_profile": active},
            active["model"],
            active["effort"],
            1,
            source_bundle=("fixture guidance", self.models),
            runtime_factory=lambda *a, **k: app,
        )
        self.assertEqual(result["decision"], "keep")
        sent = app.call.call_args_list[2].args
        self.assertEqual(sent[0], "turn/start")
        self.assertEqual(sent[1]["input"][1:-1], native)
        self.assertEqual(native[0]["text_elements"], [])
        app.call.side_effect = [
            {
                "data": [
                    {
                        "skills": [
                            {
                                "name": "model-fit",
                                "enabled": True,
                                "path": str(app.skill_file),
                            }
                        ]
                    }
                ]
            },
            {"thread": {"id": "assessment-image-only"}},
            {"turn": {"id": "assessment-image-turn"}},
        ]
        TRIAGE.assess(
            {"input": native[1:], "active_profile": active},
            active["model"],
            active["effort"],
            1,
            source_bundle=("fixture guidance", self.models),
            runtime_factory=lambda *a, **k: app,
        )
        self.assertEqual(app.call.call_args_list[-1].args[1]["input"][1:-1], native[1:])

    def test_keep_clears_repeated_current_profile(self) -> None:
        active, output = self.saved_output("writer-delegation-only")
        result = validate(output, active, self.models)
        self.assertEqual(result["decision"], "keep")
        self.assertIsNone(result["recommended_model"])
        self.assertIsNone(result["recommended_effort"])
        self.assertIsNone(result["recommended_speed"])

    def test_recommendation_accepts_other_families_from_the_same_catalog(self) -> None:
        for model in ("gpt-6.1-terra", "gpt-6-astra"):
            with self.subTest(model=model):
                active, output = self.saved_output("mail-to-search-design")
                models = {
                    **self.models.entries,
                    model: {
                        "slug": model,
                        "visibility": "list",
                        "supported_reasoning_levels": [{"effort": "medium"}],
                    },
                }
                output.update(recommended_model=model, recommended_effort="medium")
                result = validate(output, active, NativeCatalog(models))
                self.assertEqual(result["recommended_model"], model)
                self.assertEqual(result["recommended_effort"], "medium")

    def test_recommendation_rejects_catalog_target_absent_from_same_snapshot(
        self,
    ) -> None:
        active, output = self.saved_output("mail-to-search-design")
        output["recommended_model"] = "unlisted-model"
        with self.assertRaisesRegex(ValueError, "catalog"):
            validate(output, active, self.models)

    def test_unknown_speed_cannot_be_changed(self) -> None:
        active, output = self.saved_output("speed-only-fast")
        active["speed"] = None
        output["active_speed"] = None
        with self.assertRaisesRegex(ValueError, "unknown speed"):
            validate(output, active, self.models)

    def test_active_profile_mismatch_is_rejected(self) -> None:
        active, output = self.saved_output("mail-collection")
        output["active_model"] = "gpt-6.1-sol"
        with self.assertRaisesRegex(ValueError, "active_model"):
            validate(output, active, self.models)

    def test_lighter_same_model_cannot_increase_effort(self) -> None:
        active, output = self.saved_output("design-to-issue-draft")
        active["effort"] = "low"
        output["active_effort"] = "low"
        output["recommended_effort"] = "high"
        with self.assertRaisesRegex(ValueError, "effort direction"):
            validate(output, active, self.models)

    def test_stronger_same_model_cannot_decrease_effort(self) -> None:
        active, output = self.saved_output("design-to-issue-draft")
        output["decision"] = "recommend_stronger"
        with self.assertRaisesRegex(ValueError, "effort direction"):
            validate(output, active, self.models)

    def test_missing_catalog_does_not_become_keep(self) -> None:
        active, _ = self.saved_output("mail-collection")
        request = {"task": "Собери даты и темы писем", "active_profile": active}
        visible = io.StringIO()
        with (
            patch("sys.argv", ["triage.py"]),
            patch("sys.stdin", io.StringIO(json.dumps(request))),
            patch(
                "model_fit.infrastructure.adapters.codex.sources.sources",
                side_effect=SourceUnavailable("Codex model catalog"),
            ),
            redirect_stdout(visible),
        ):
            code = CLI.main()
        self.assertEqual(code, 1)
        result = json.loads(visible.getvalue())
        schema = json.loads(
            (ROOT / "plugins/model-fit/src/assessment/decision.schema.json").read_text()
        )
        self.assertEqual(set(result), set(schema["required"]))
        self.assertEqual(result["decision"], "unknown")
        self.assertEqual(result["active_model"], active["model"])
        self.assertEqual(result["active_effort"], active["effort"])
        self.assertEqual(result["active_speed"], active["speed"])
        self.assertIsNone(result["recommended_model"])
        self.assertIsNone(result["recommended_effort"])
        self.assertIsNone(result["recommended_speed"])

    def test_assessment_client_distinguishes_software_failure_from_abstention(self):
        active, _ = self.saved_output("mail-collection")
        request = {"task": "fixture", "active_profile": active}
        result = empty_decision(active, "unknown", "fixture")
        for stderr, expected in (
            ("", None),
            ("model-fit triage error: TimeoutError\n", TimeoutError),
            ("model-fit triage error: SourceUnavailable\n", SourceUnavailable),
            (
                "model-fit triage error: ProviderProtocolError\nprivate-sentinel\n",
                RuntimeError,
            ),
        ):
            with (
                self.subTest(expected=expected),
                patch.object(
                    ASSESSMENT_CLIENT.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        [], 1, json.dumps(result), stderr
                    ),
                ),
            ):
                if expected is None:
                    self.assertEqual(
                        ASSESSMENT_CLIENT.triage(request)["decision"], "unknown"
                    )
                else:
                    with self.assertRaises(expected) as caught:
                        ASSESSMENT_CLIENT.triage(request)
                    self.assertNotIn("private-sentinel", str(caught.exception))

    def test_malformed_request_emits_no_decision(self) -> None:
        active, _ = self.saved_output("mail-collection")
        malformed = (
            {"active_profile": active},
            {"active_profile": active, "input": None},
            {"active_profile": active, "input": []},
            {"task": "   ", "active_profile": active},
            {"task": "Собери письма", "active_profile": active, "context": []},
            {"task": "Собери письма", "active_profile": active, "prior_choice": 1},
            {
                "task": "Собери письма",
                "active_profile": active,
                "prior_choice": "останься на этом профиле",
            },
            {
                "task": "Собери письма",
                "active_profile": active,
                "prior_choice": {
                    "user_selected": True,
                    "same_work": False,
                    "profile": active,
                },
            },
        )
        for request in malformed:
            with self.subTest(request=request):
                visible = io.StringIO()
                with (
                    patch("sys.argv", ["triage.py"]),
                    patch(
                        "sys.stdin",
                        io.StringIO(json.dumps(request, ensure_ascii=False)),
                    ),
                    patch.object(
                        SOURCES,
                        "sources",
                        side_effect=AssertionError("source lookup started"),
                    ),
                    redirect_stdout(visible),
                    redirect_stderr(io.StringIO()),
                ):
                    code = CLI.main()
                self.assertEqual(code, 2)
                self.assertEqual(visible.getvalue(), "")

    def test_confirmed_choice_skips_sources_and_model(self) -> None:
        active, _ = self.saved_output("user-choice-preserved")
        request = {
            "task": "Продолжи ту же работу",
            "active_profile": active,
            "prior_choice": {
                "user_selected": True,
                "same_work": True,
                "profile": active,
            },
        }
        diagnostics = {}
        with patch(
            "model_fit.infrastructure.adapters.codex.sources.sources",
            side_effect=AssertionError("model started"),
        ):
            result = TRIAGE.assess(
                request, "gpt-6.1-sol", "low", 180, diagnostics=diagnostics
            )
        self.assertEqual(result["decision"], "keep")
        self.assertIsNone(result["recommended_model"])
        self.assertEqual(result["active_model"], active["model"])
        self.assertTrue(diagnostics["user_choice_bypass"])
        self.assertEqual(diagnostics["agent_messages"], 0)
        self.assertIsNone(diagnostics["usage"])
        visible = io.StringIO()
        with (
            patch("sys.argv", ["triage.py"]),
            patch("sys.stdin", io.StringIO(json.dumps(request, ensure_ascii=False))),
            patch(
                "model_fit.infrastructure.adapters.codex.sources.sources",
                side_effect=AssertionError("model started"),
            ),
            redirect_stdout(visible),
        ):
            code = CLI.main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(visible.getvalue())["decision"], "keep")


if __name__ == "__main__":
    unittest.main()


class PartialPreflightEvidenceTests(unittest.TestCase):
    def test_wait_and_tool_failure_publish_available_native_events_and_cumulative_usage(
        self,
    ):
        from unittest.mock import Mock

        model = "gpt-6-luna"
        models = {
            model: {
                "visibility": "list",
                "supported_reasoning_levels": [{"effort": "low"}],
                "additional_speed_tiers": [],
            }
        }
        request = {
            "task": "bounded fixture request",
            "active_profile": {"model": model, "effort": "low", "speed": None},
        }
        total = {
            "inputTokens": 900,
            "outputTokens": 100,
            "totalTokens": 1000,
            "cachedInputTokens": 700,
            "reasoningOutputTokens": 12,
        }
        for failure in ["wait", "tool"]:
            app = Mock()
            app.skill_file = Path("/fixture/SKILL.md")
            app.__enter__ = Mock(return_value=app)
            app.__exit__ = Mock(return_value=None)
            app.events = [
                {
                    "method": "thread/settings/updated",
                    "params": {
                        "threadSettings": {
                            "model": model,
                            "effort": "low",
                            "serviceTier": None,
                        }
                    },
                },
                {
                    "method": "thread/tokenUsage/updated",
                    "params": {
                        "tokenUsage": {"total": total, "last": {"totalTokens": 3}}
                    },
                },
            ]
            if failure == "tool":
                app.events.append(
                    {
                        "method": "item/started",
                        "params": {"item": {"type": "mcpToolCall"}},
                    }
                )
            app.call.side_effect = [
                {
                    "data": [
                        {
                            "skills": [
                                {
                                    "name": "model-fit",
                                    "enabled": True,
                                    "path": str(app.skill_file),
                                }
                            ]
                        }
                    ]
                },
                {"thread": {"id": "thread"}},
                {"turn": {"id": "turn"}},
            ]
            app.wait_turn.side_effect = (
                TimeoutError("fixture timeout") if failure == "wait" else None
            )
            app.wait_turn.return_value = "completed"
            diagnostics = {}
            with (
                self.subTest(failure=failure),
                patch(
                    "model_fit.infrastructure.adapters.codex.transport.assessment.session.AppServer",
                    return_value=app,
                ),
                self.assertRaises((TimeoutError, RuntimeError)),
            ):
                TRIAGE.assess(
                    request, model, "low", 1, ("frozen fixture", models), diagnostics
                )
            self.assertEqual(diagnostics["events"], app.events)
            self.assertEqual(diagnostics["usage"]["total"], total)
            app.__exit__.assert_called_once()
