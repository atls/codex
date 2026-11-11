"""Promptfoo adapter to the production Model Fit assessor."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[3]
import vector_prime.entrypoints.cli.assess as TRIAGE
from assessment.scenarios import catalog_models, fixture_context, load_scenarios
from vector_prime.application.assessment.exceptions.source_unavailable import (
    SourceUnavailable,
)
from vector_prime.application.assessment.helpers.decision import empty_decision


def provider_evidence(diagnostics, request, prompt, error=None):
    events = diagnostics.get("events")
    usage = diagnostics.get("usage")
    if not isinstance(usage, dict) and isinstance(events, list):
        usage = next(
            (
                (event.get("params") or {}).get("tokenUsage")
                for event in reversed(events)
                if event.get("method") == "thread/tokenUsage/updated"
            ),
            None,
        )
    total = usage.get("total") if isinstance(usage, dict) else None
    no_model = (
        diagnostics.get("source_failure_simulation") is True
        or diagnostics.get("user_choice_bypass") is True
    )
    profile = next(
        (
            (event.get("params") or {}).get("threadSettings")
            for event in reversed(events or [])
            if event.get("method") == "thread/settings/updated"
        ),
        None,
    )
    metadata = {
        key: diagnostics.get(key)
        for key in (
            "prompt_sha256",
            "skill_item_seen",
            "tool_types",
            "agent_messages",
            "user_choice_bypass",
            "source_failure_simulation",
            "source_mode",
            "work_relation",
        )
    }
    metadata.update(
        {
            "model_turns": sum(
                (event.get("method") == "turn/started" for event in events)
            )
            if isinstance(events, list)
            else 0
            if no_model
            else None,
            "usage_status": "known"
            if total is not None
            else "not-applicable"
            if no_model
            else "unknown",
            "observed_launch_profile": {
                key: profile.get(key) for key in ("model", "effort", "serviceTier")
            }
            if isinstance(profile, dict)
            else None,
            "sampling_trace": {
                "status": "not-invoked" if no_model else "unknown",
                "reason": "No independent preflight sampling trace configured",
            },
        }
    )
    result = {
        "metadata": metadata,
        "raw": json.dumps(
            {
                "input_prompt": prompt,
                "request": request,
                "events": events,
                "usage": usage,
                "diagnostics": diagnostics,
                "error": error,
            },
            ensure_ascii=False,
        ),
    }
    if isinstance(total, dict):
        keys = {
            "total": "totalTokens",
            "prompt": "inputTokens",
            "completion": "outputTokens",
            "cached": "cachedInputTokens",
            "cacheWrite": "cacheWriteInputTokens",
        }
        result["tokenUsage"] = {
            target: total[source]
            for target, source in keys.items()
            if type(total.get(source)) is int
        }
        if type(total.get("reasoningOutputTokens")) is int:
            result["tokenUsage"]["completionDetails"] = {
                "reasoning": total["reasoningOutputTokens"]
            }
    return result


def call_api(prompt, options, context):
    config = options.get("config", {})
    diagnostics = {}
    request = None
    try:
        supplied = json.loads(prompt)
        bundle = None
        case = None
        if "request" in supplied:
            request = supplied["request"]
            diagnostics["source_mode"] = "live-official-sources"
        else:
            case = load_scenarios([supplied["case_id"]])[0]
            if case.get("implicit_selection_control"):
                raise ValueError("Ordinary dialogue has a separate native control")
            active = {key: case[key] for key in ("model", "effort", "speed")}
            request = {"task": case["task_prompt"], "active_profile": active}
            if case.get("prior_choice"):
                request["prior_choice"] = {
                    "user_selected": True,
                    "same_work": True,
                    "profile": active,
                }
            if fixture := fixture_context(case):
                request["context"] = fixture
            sources = (HERE / "fixtures/preflight-sources-2026-10-16.txt").read_text()
            bundle = (sources, catalog_models(sources))
            diagnostics["source_mode"] = "frozen-historical-sources"
        if case and case.get("source_failure"):
            answer = empty_decision(
                active,
                "unknown",
                "Required source unavailable: " + case["source_failure"],
            )
            diagnostics["source_failure_simulation"] = True
        else:
            answer = TRIAGE.assess(
                request,
                config.get("model", "gpt-6.1-sol"),
                config.get("effort", "low"),
                config.get("turn_timeout_seconds", 180),
                bundle,
                diagnostics,
                codex_path=config.get("codex_path", "codex"),
            )
        return {
            "output": json.dumps(answer, ensure_ascii=False),
            **provider_evidence(diagnostics, request, prompt),
        }
    except (
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        OSError,
        TimeoutError,
        SourceUnavailable,
    ) as error:
        return {
            "error": type(error).__name__,
            **provider_evidence(
                diagnostics,
                request,
                prompt,
                {"type": type(error).__name__, "message": str(error)},
            ),
        }
