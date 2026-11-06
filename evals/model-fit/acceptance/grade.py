"""Deterministic private native media acceptance; no grader inference."""

import base64
import io
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageStat


def image_color(item, retained_images=()):
    if item["type"] == "localImage":
        source = item["path"]
        if not Path(source).is_file():
            matching = [
                entry for entry in retained_images if entry["originalPath"] == source
            ]
            if len(matching) != 1:
                raise ValueError("Original image bytes were not retained")
            source = matching[0]["retainedPath"]
            if (
                hashlib.sha256(Path(source).read_bytes()).hexdigest()
                != matching[0]["sha256"]
            ):
                raise ValueError("Retained image hash differs")
    elif item["type"] == "image":
        url = item["url"]
        if not url.startswith("data:image/") or ";base64," not in url:
            raise ValueError("Native image payload is unavailable")
        source = io.BytesIO(base64.b64decode(url.split(",", 1)[1], validate=True))
    else:
        raise ValueError("Unexpected native input item")
    with Image.open(source) as image:
        red, green, blue = ImageStat.Stat(image.convert("RGB")).mean
    if red > 230 and green < 25 and blue < 25:
        return "red"
    if blue > 230 and red < 25 and green < 25:
        return "blue"
    return "other"


def get_assert(output, context):
    evidence = Path(context["vars"]["evidence"])
    home = Path(context["vars"]["home"])
    result = {
        "pass": False,
        "scope": "native ephemeral host; not Desktop sidebar/full switch",
        "checks": {},
    }
    try:
        raw = context["providerResponse"]["raw"]
        raw = json.loads(raw) if isinstance(raw, str) else raw
        metadata = context["providerResponse"]["metadata"]["codexAppServer"]
        thread_id, turn_id = metadata["threadId"], metadata["turnId"]
        notifications = raw.get("notifications", [])
        messages = [
            item
            for item in raw["items"]
            if item["type"] in {"user_message", "userMessage"}
        ]
        assert len(messages) == 1, "Original native user message is not unique"
        content = messages[0]["content"]
        text = "".join(item["text"] for item in content if item["type"] == "text")
        images = [item for item in content if item["type"] in {"image", "localImage"}]
        colors = [
            image_color(item, context["vars"].get("retained_images", []))
            for item in images
        ]
        assert text == context["vars"]["prompt"] and colors == ["red", "blue"], (
            "Native input text/image order changed"
        )
        assert all(
            item["type"] in {"text", "image", "localImage"} for item in content
        ), "Unexpected input item"
        result["checks"]["orderedNativeInput"] = True
        captures = [
            json.loads(line)
            for line in (
                (home / "acceptance-hook-events.jsonl")
                if (home / "acceptance-hook-events.jsonl").is_file()
                else evidence / "acceptance-hook-events.jsonl"
            )
            .read_text()
            .splitlines()
        ]
        submits = [
            row
            for row in captures
            if row["event"].get("hook_event_name") == "UserPromptSubmit"
            and row["event"].get("session_id") == thread_id
            and row["event"].get("turn_id") == turn_id
        ]
        assert len(submits) == 1 and submits[0]["returncode"] == 0, (
            "Candidate hook submit execution is absent"
        )
        hook_output = json.loads(submits[0]["stdout"])
        assert (
            hook_output.get("hookSpecificOutput", {}).get("hookEventName")
            == "UserPromptSubmit"
        ), "Deferred assessment instruction is absent"
        assert (submits[0].get("state_snapshot") or {}).get("pending_assessment"), (
            "Pending assessment was not registered"
        )
        assert submits[0]["event"]["prompt"] == context["vars"]["prompt"], (
            "Hook text projection changed"
        )
        native_hooks = [
            event
            for event in notifications
            if event.get("method", "").startswith("hook/")
        ]
        assert any(
            event.get("method") == "hook/completed"
            and event.get("params", {}).get("threadId") == thread_id
            and event["params"].get("turnId") == turn_id
            and event["params"].get("run", {}).get("eventName") == "userPromptSubmit"
            and event["params"]["run"].get("status") == "completed"
            and Path(event["params"]["run"]["sourcePath"])
            == Path(context["vars"]["plugin"]) / "hooks/hooks.json"
            for event in native_hooks
        ), "Exact native candidate hook completion is absent"
        result["checks"]["exactCandidateDeferredHook"] = True
        audit = [
            json.loads(line)
            for line in (
                (home / ".tmp/model-fit-hook-audit" / (thread_id + ".jsonl"))
                if home.exists()
                else evidence / "audit" / (thread_id + ".jsonl")
            )
            .read_text()
            .splitlines()
        ]
        selected = [row for row in audit if row.get("turn_id") == turn_id]
        assert any(row["outcome"] == "auto_session_unavailable" for row in selected), (
            "Exact fallback audit is absent"
        )
        assert not any(
            row["outcome"].startswith("auto_queue") or row["outcome"] == "auto_handoff"
            for row in selected
        ), "Unexpected handoff/queue"
        state_path = (
            home / ".tmp/model-fit-auto-switch" / (thread_id + ".json")
            if home.exists()
            else evidence / "state" / (thread_id + ".json")
        )
        snapshots = [
            row.get("state_snapshot")
            for row in captures
            if row["event"].get("session_id") == thread_id
            and row["event"].get("turn_id") == turn_id
        ]
        if state_path.is_file():
            snapshots.append(json.loads(state_path.read_text()))
        assert any(
            state
            and state.get("phase") == "passed"
            and state.get("source_turn_id") == turn_id
            and not state.get("pending_assessment")
            for state in snapshots
        ), "Unknown assessment did not release original turn"
        result["checks"]["noQueueOrReconstruction"] = True
        assert raw["turn"]["id"] == turn_id and raw["turn"]["status"] == "completed", (
            "Original turn did not complete"
        )
        answer = json.loads(output)
        assert (
            answer.get("colors") == ["red", "blue"] and answer.get("imageCount") == 2
        ), "Image answer is incorrect"
        settings = [
            event["params"]["threadSettings"]
            for event in notifications
            if event.get("method") == "thread/settings/updated"
        ]
        assert (
            settings
            and settings[-1]["model"] == "gpt-6-luna"
            and settings[-1]["effort"] == "medium"
            and settings[-1].get("serviceTier") is None
        ), "Observed launch profile differs"
        result["checks"]["originalTurnCompletedWithImageAnswer"] = True
        result.update(
            {
                "pass": True,
                "colors": colors,
                "nativeInputItemTypes": [item["type"] for item in content],
                "nativeHookEventCount": len(native_hooks),
                "auditOutcomes": [row["outcome"] for row in selected],
                "launchModel": settings[-1]["model"],
                "launchEffort": settings[-1]["effort"],
                "usageTotal": raw.get("tokenUsage", {}).get("total"),
            }
        )
        (evidence / "native-source-items.json").write_text(
            json.dumps(content, ensure_ascii=False)
        )
    except (AssertionError, KeyError, TypeError, ValueError, OSError) as error:
        result["errorType"] = type(error).__name__
        result["reason"] = str(error)
    Path(context["vars"].get("grade_output", evidence / "grade.json")).write_text(
        json.dumps(result, indent=2)
    )
    return {
        "pass": result["pass"],
        "score": 1 if result["pass"] else 0,
        "reason": "Native media acceptance passed"
        if result["pass"]
        else json.dumps(result),
    }
