"""Prepare a selected thread for a verified Model Fit profile handoff."""

from __future__ import annotations
import shlex
import time
from pathlib import Path
from typing import Any
from model_fit.input import prompt_digest
from model_fit.queue import (
    RPC_TIMEOUT_SECONDS,
    queued_ids,
    replay_finished,
    source_interrupted,
)
from model_fit.state import locked_state, read_state, write_state
from model_fit.audit import record_audit
from model_fit.recommendation import RECOMMENDATIONS, hook_output

CONTROL_PROMPT = "Model Fit: заверши технический перенос запроса"
REPLAY_CONTEXT = "Служебная метка model-fit-replay в конце запроса обозначает перенос между ходами. Игнорируй её при выполнении исходной задачи."


def control_context(
    thread_id: str, turn_id: str, state: dict[str, Any]
) -> dict[str, Any]:
    model = state["target_model"]
    effort = state["target_effort"]
    command = queue_command(thread_id, turn_id)
    instruction = (
        "Model Fit выбрал смену профиля. Этот ход только технический: не выполняй исходную задачу "
        "и не вызывай её предметные инструменты. Исходный текст и все вложения "
        "утилита перенесёт из нативного сообщения целиком; повторная отправка "
        "пользователем не нужна. Сначала вызови "
        f"mcp__codex_app__send_message_to_thread для этого же threadId {thread_id} "
        f"с model={model}, thinking={effort} и коротким prompt "
        f"«{CONTROL_PROMPT}». "
        f"После успешного вызова запусти `{command}`. "
        "Если любой шаг не удался, не продолжай исходную задачу на текущем профиле; "
        "сообщи точную ошибку. После успешной постановки в очередь закончи ход коротким "
        "техническим ответом. Исходный запрос запустится следующим ходом автоматически. "
        f"Рекомендация OpenAI: {state['official_guidance']} "
        f"Вывод для задачи: {state['task_inference']} Источник: {state['official_source_url']}"
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": instruction,
        }
    }


def queue_command(thread_id: str, turn_id: str) -> str:
    return (
        f"python3 {shlex.quote(str(Path(__file__).resolve()))} queue "
        f"--thread-id {shlex.quote(thread_id)} --turn-id {shlex.quote(turn_id)}"
    )


def block_prompt(
    thread_id: str, turn_id: str, reason_code: str, reason: str, phase: str
) -> dict[str, str]:
    record_audit(
        thread_id,
        turn_id,
        "auto_prompt_block",
        {
            "hook_event": "UserPromptSubmit",
            "reason_code": reason_code,
            "state_phase": phase,
        },
    )
    return {"decision": "block", "reason": reason}


def prepare(
    event: dict[str, Any], reader_factory: Any, session_input: Any, triage: Any
) -> dict[str, Any] | None:
    thread_id = event["session_id"]
    turn_id = event["turn_id"]
    prompt = event["prompt"]
    if not all(
        isinstance(value, str) and value for value in (thread_id, turn_id)
    ) or not isinstance(prompt, str):
        raise ValueError("Incomplete Desktop hook input")
    with locked_state(thread_id, operation="prompt_submit", turn_id=turn_id) as path:
        prior = read_state(path)
        if prior is not None and prior["phase"] == "passed":
            if prior["source_turn_id"] == turn_id:
                record_audit(thread_id, turn_id, "auto_steer")
                return None
            path.unlink()
            prior = None
        if prior is not None:
            if prior["phase"] == "attempting":
                return block_prompt(
                    thread_id,
                    turn_id,
                    "queue_outcome_unknown",
                    "Model Fit: исход постановки прежнего запроса в очередь неизвестен; повторная постановка запрещена.",
                    prior["phase"],
                )
            if prior["phase"] == "rejected":
                if prior["source_turn_id"] == turn_id:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "queue_rejected_same_turn",
                        "Model Fit: технический ход завершился отказом очереди; новое поручение нужно отправить отдельным ходом.",
                        prior["phase"],
                    )
                path.unlink()
            if prior["phase"] == "ready":
                if prior["source_turn_id"] == turn_id:
                    if prior["prompt_digest"] == prompt_digest(prompt):
                        return control_context(thread_id, turn_id, prior)
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "technical_turn_steered",
                        "Model Fit: технический ход уже начат; новое поручение отправь отдельным ходом.",
                        prior["phase"],
                    )
                path.unlink()
            elif prior["phase"] == "queued":
                if prior.get("replay_turn_id") == turn_id:
                    record_audit(thread_id, turn_id, "auto_steer")
                    return None
                if prior["source_turn_id"] == turn_id:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "source_turn_already_queued",
                        "Model Fit: технический ход уже поставил запрос в очередь; новое поручение отправь отдельным ходом.",
                        prior["phase"],
                    )
                if prior.get("queued_prompt_digest") == prompt_digest(prompt):
                    if prior.get("replay_turn_id") not in (None, turn_id):
                        return block_prompt(
                            thread_id,
                            turn_id,
                            "duplicate_replay",
                            "Model Fit: повторное продолжение запроса запрещено.",
                            prior["phase"],
                        )
                    with reader_factory(event["cwd"]) as app:
                        if prior["queued_submission_id"] in queued_ids(app, thread_id):
                            return block_prompt(
                                thread_id,
                                turn_id,
                                "replay_still_queued",
                                "Model Fit: продолжение ещё находится в очереди.",
                                prior["phase"],
                            )
                    selected = session_input(event)["active_profile"]
                    if (selected["model"], selected["effort"]) != (
                        prior["target_model"],
                        prior["target_effort"],
                    ):
                        return block_prompt(
                            thread_id,
                            turn_id,
                            "replay_wrong_profile",
                            "Model Fit: запрос из очереди пришёл на неверном профиле.",
                            prior["phase"],
                        )
                    prior["replay_turn_id"] = turn_id
                    write_state(path, prior)
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": REPLAY_CONTEXT,
                        }
                    }
                with reader_factory(event["cwd"]) as app:
                    if prior["queued_submission_id"] in queued_ids(app, thread_id):
                        deleted = app.call(
                            "thread/queue/delete",
                            {
                                "threadId": thread_id,
                                "queuedSubmissionId": prior["queued_submission_id"],
                            },
                            RPC_TIMEOUT_SECONDS,
                        ).get("deleted")
                        if not deleted:
                            return block_prompt(
                                thread_id,
                                turn_id,
                                "prior_replay_starting",
                                "Model Fit: прежний запрос уже запускается; повтори новое поручение после его завершения.",
                                prior["phase"],
                            )
                    else:
                        if not replay_finished(app, thread_id, prior) and not (
                            prior.get("replay_turn_id") is None
                            and source_interrupted(
                                app, thread_id, prior["source_turn_id"]
                            )
                        ):
                            return block_prompt(
                                thread_id,
                                turn_id,
                                "prior_replay_running",
                                "Model Fit: прежний запрос выполняется; повтори новое поручение после его завершения.",
                                prior["phase"],
                            )
                path.unlink()

    request = session_input(event)
    result = triage(request)
    if result["decision"] in {"keep", "unknown"}:
        with locked_state(
            thread_id, operation="prompt_submit", turn_id=turn_id
        ) as path:
            write_state(path, {"phase": "passed", "source_turn_id": turn_id})
        return None if result["decision"] == "keep" else hook_output(result)
    if result["decision"] not in RECOMMENDATIONS:
        raise ValueError("Unsupported triage decision")
    manual = hook_output(result)
    target_model = result.get("recommended_model") or result["active_model"]
    target_effort = result.get("recommended_effort") or result["active_effort"]
    if result.get("recommended_speed") not in (
        None,
        request["active_profile"]["speed"],
    ):
        manual["reason"] += (
            f" Автоматический перенос скорости недоступен; целевое значение: {result['recommended_speed']}."
        )
        record_audit(
            thread_id,
            turn_id,
            "auto_fallback",
            {
                "hook_event": "UserPromptSubmit",
                "reason_code": "speed_switch_unsupported",
            },
        )
        return manual
    if (target_model, target_effort) == (
        result["active_model"],
        result["active_effort"],
    ):
        record_audit(
            thread_id,
            turn_id,
            "auto_fallback",
            {
                "hook_event": "UserPromptSubmit",
                "reason_code": "no_model_or_effort_change",
            },
        )
        return manual
    try:
        with reader_factory(event["cwd"]) as app:
            queued_ids(app, thread_id)
    except (OSError, ValueError, RuntimeError, TimeoutError):
        manual["reason"] += " Автоматическая очередь недоступна."
        record_audit(
            thread_id,
            turn_id,
            "auto_fallback",
            {
                "hook_event": "UserPromptSubmit",
                "reason_code": "queue_preflight_unavailable",
            },
        )
        return manual
    state = {
        "phase": "ready",
        "created_at": int(time.time()),
        "source_turn_id": turn_id,
        "prompt": prompt,
        "prompt_digest": prompt_digest(prompt),
        "target_model": target_model,
        "target_effort": target_effort,
        "official_source_url": result["official_source_url"],
        "official_guidance": result["official_guidance"],
        "task_inference": result["task_inference"],
    }
    with locked_state(thread_id, operation="prompt_submit", turn_id=turn_id) as path:
        write_state(path, state)
    return control_context(thread_id, turn_id, state)
