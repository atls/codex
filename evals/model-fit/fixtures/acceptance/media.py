import json
from PIL import Image


def media_context(root, empty=False):
    home = root / "home"
    home.mkdir()
    evidence = root / "evidence"
    evidence.mkdir()
    Image.new("RGB", (8, 8), "red").save(root / "first.png")
    Image.new("RGB", (8, 8), "blue").save(root / "second.png")
    prompt = "" if empty else "name colors"
    content = [
        {"type": "text", "text": prompt},
        {"type": "localImage", "path": str(root / "first.png")},
        {"type": "localImage", "path": str(root / "second.png")},
    ]
    warning = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "assess",
            }
        }
    )
    (home / "acceptance-hook-events.jsonl").write_text(
        json.dumps(
            {
                "event": {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "thread",
                    "turn_id": "turn",
                    "prompt": prompt,
                },
                "state_snapshot": {
                    "phase": "submitted",
                    "pending_assessment": {"generation": "fixture"},
                },
                "returncode": 0,
                "stdout": warning,
            }
        )
        + "\n"
    )
    audit = home / ".tmp/model-fit-hook-audit"
    audit.mkdir(parents=True)
    (audit / "thread.jsonl").write_text(
        json.dumps({"turn_id": "turn", "outcome": "auto_session_unavailable"}) + "\n"
    )
    state = home / ".tmp/model-fit-auto-switch"
    state.mkdir()
    (state / "thread.json").write_text(
        json.dumps({"phase": "passed", "source_turn_id": "turn"})
    )
    raw = {
        "items": [{"type": "user_message", "content": content}],
        "turn": {"id": "turn", "status": "completed"},
        "notifications": [
            {
                "method": "hook/completed",
                "params": {
                    "threadId": "thread",
                    "turnId": "turn",
                    "run": {
                        "eventName": "userPromptSubmit",
                        "status": "completed",
                        "sourcePath": str(home / "hooks/hooks.json"),
                        "entries": ["[...]"],
                    },
                },
            },
            {
                "method": "thread/settings/updated",
                "params": {
                    "threadSettings": {
                        "model": "gpt-6-luna",
                        "effort": "medium",
                        "serviceTier": None,
                    }
                },
            },
        ],
    }
    context = {
        "vars": {
            "home": str(home),
            "evidence": str(evidence),
            "prompt": prompt,
            "plugin": str(home),
        },
        "providerResponse": {
            "raw": raw,
            "metadata": {"codexAppServer": {"threadId": "thread", "turnId": "turn"}},
        },
    }
    return context
