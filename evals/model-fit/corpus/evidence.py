"""Cumulative native stage ledgers and observed launch settings."""

import json


def raw_response(response):
    raw = (response or {}).get("raw")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def events(response):
    raw = raw_response(response)
    return [
        event
        for event in [*(raw.get("events") or []), *(raw.get("notifications") or [])]
        if isinstance(event, dict)
    ]


def cumulative_usage(response):
    raw = raw_response(response)
    for ledger in [raw.get("tokenUsage"), raw.get("usage")]:
        if isinstance(ledger, dict) and ledger.get("total") is not None:
            return ledger["total"]
    updates = [
        (event.get("params") or {}).get("tokenUsage", {})
        for event in events(response)
        if event.get("method") == "thread/tokenUsage/updated"
    ]
    return updates[-1].get("total") if updates else None


def observed_profile(response):
    settings = [
        (event.get("params") or {}).get("threadSettings")
        for event in events(response)
        if event.get("method") == "thread/settings/updated"
    ]
    return (
        {key: settings[-1].get(key) for key in ["model", "effort", "serviceTier"]}
        if settings and settings[-1]
        else None
    )


def normalized_usage(total):
    if not isinstance(total, dict):
        return None
    keys = {
        "total": "totalTokens",
        "prompt": "inputTokens",
        "completion": "outputTokens",
        "cached": "cachedInputTokens",
        "cacheWrite": "cacheWriteInputTokens",
    }
    result = {
        target: total[source]
        for target, source in keys.items()
        if type(total.get(source)) in (int, float)
    }
    if type(total.get("reasoningOutputTokens")) in (int, float):
        result["completionDetails"] = {"reasoning": total["reasoningOutputTokens"]}
    return result
