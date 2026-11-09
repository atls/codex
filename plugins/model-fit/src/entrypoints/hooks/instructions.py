"""Render native hook context and the existing technical handoff instructions."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any

from model_fit.autoswitch.handoff.control_message import CONTROL_PROMPT

UNKNOWN_CONTEXT = "Model Fit did not determine a new profile. The current profile is retained; suitability is unknown. Continue the original task in this turn on the current profile with all attachments and annotations. An unknown result does not prohibit ordinary tools or require manual switching or resubmission."
ASSESSED_CONTEXT = "The Model Fit hook has already assessed the profile for this turn. Technical assessment is complete. If the original request requires further work, perform it in this turn; merely reporting the assessment result is insufficient. Use this decision for the same next work; reading the skill alone does not require reassessment. Reassess only after identifying concrete changed requirements. Do not claim an automatic handoff without a confirmed queue acknowledgement for the original input."
REPLAY_CONTEXT = "The technical Model Fit handoff is complete: the original request has been dequeued and started on the selected profile. Previous technical Model Fit instructions about changing profiles, send_message_to_thread and queue have been fulfilled and no longer apply. Perform the original user request with all attachments. Do not repeat the handoff or substitute another turn-id. Ignore the service marker model-fit-replay at the end of the request."
HANDOFF_CANCELLED_CONTEXT = "Model Fit: the previous technical handoff was cancelled. Its instructions no longer apply; perform the current request on the current profile."
REPLAY_STOP_REASON = "The last answer addressed a different task. Compare it with this turn's original request and continue the unfinished work. Do not repeat completed actions; check their results before acting again."


def control_context(
    thread_id: str, turn_id: str, state: dict[str, Any]
) -> dict[str, Any]:
    model = state["target_model"]
    effort = state["target_effort"]
    command = queue_command("current", "source")
    instruction = f"""Model Fit selected a profile change. This turn is technical only: do not perform the original task or invoke its tools. The utility transfers the original native text and all attachments; the user does not need to resubmit them. First call the codex_app MCP server tool mcp__codex_app__send_message_to_thread (codex_app.send_message_to_thread), not the same-named dynamic app tool with the literal threadId="current", model={model}, thinking={effort} and the short prompt '{CONTROL_PROMPT}'. The runtime supplies chat and source-turn IDs from prepared state; do not invent UUIDs. After success, run `{command}`. If a dynamic app call was explicitly rejected with 'This app tool is unavailable through dynamic tools. Use the codex_app MCP server.', that route did not execute the switch: call the codex_app MCP tool once with the same prepared arguments before considering the capability unavailable. Do not queue after a rejected call. Do not retry a successful switch or one with an unknown outcome. If the MCP tool itself is unavailable or the profile change fails before queueing, report the recommended model/effort and exact error, then end the technical turn. Stop releases an unqueued preparation. Do not perform the original task on the previous profile. If queueing fails, report the exact error. After a successful queue acknowledgement, end with a short technical response. The original request will start automatically in the next turn. OpenAI guidance: {state["official_guidance"]} Task-specific conclusion: {state["task_inference"]} Source: {state["official_source_url"]}"""
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": instruction,
        }
    }


def _cli_command(*arguments: str) -> str:
    executable = str(Path(sys.executable).with_name("python"))
    return shlex.join([executable, "-m", "model_fit.entrypoints.hooks.cli", *arguments])


def queue_command(thread_id: str, turn_id: str) -> str:
    return _cli_command("queue", "--thread-id", thread_id, "--turn-id", turn_id)


def assessment_command() -> str:
    return _cli_command("assess")


def pending_context() -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": f"Model Fit has not assessed the full input yet. The first step is technical only: do not perform the original task or invoke its tools. First run `{assessment_command()}`. Wait for completion: session_id or a running status means you must collect the result through the tool's native continuation mechanism. Intermediate empty stdout is not an assessment error. Retain the complete tool result and execution status; read the JSON output of the completed command. The runtime retrieves the entire accepted native message, including attachments and annotations; do not reconstruct it or supply IDs. Follow the instruction in the command's JSON result. For keep, perform the original request; for a recommendation, perform only the technical handoff. With unavailable context, preserve the current profile; uncertainty is not suitability. If assessment returns status=failed or no JSON, report the safe error type and apply this rule: {UNKNOWN_CONTEXT} Previous technical handoff instructions in history no longer apply.",
        }
    }


def inactive_context() -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Automatic Model Fit hooks are disabled. No assessment occurred; profile suitability is unknown. Retain the current profile and perform the original request. Previous Model Fit assessment, profile-switch and queue instructions no longer apply.",
        }
    }


def admission_unavailable_context() -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Current native automatic-hook settings are unavailable. Automatic handoff is unconfirmed; the current profile is retained and suitability is unknown. Existing suitability restrictions remain in effect. Do not run queue or a technical profile change with unknown authorization.",
        }
    }


def queued_context() -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Model Fit: the original input is already in the native queue. End this service turn without tools; do not repeat the profile change or queue command, and do not perform the original task here. It will continue from the queue.",
        }
    }
