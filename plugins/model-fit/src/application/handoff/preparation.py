"""Opt-in Desktop Model Fit handoff to a queued turn on the selected profile."""

from __future__ import annotations

from typing import Any

from model_fit.application.handoff.assessment import apply_assessment
from model_fit.application.handoff.denial import block_prompt
from model_fit.application.handoff.dependencies import Dependencies
from model_fit.application.handoff.recommendation import (
    blocking_recommendation,
    load_blocking_recommendation,
)

from .lifecycle import Lifecycle
from .requests.prompt import Prompt


def prepare(
    event: Prompt,
    *,
    dependencies: Dependencies,
    expected_submission: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    thread_id = event.thread_id
    turn_id = event.turn_id
    prompt = event.text
    if not all(
        (isinstance(value, str) and value for value in (thread_id, turn_id))
    ) or not isinstance(prompt, str):
        raise ValueError("Incomplete Desktop hook input")
    pending = None
    profile_context_turn_id = None
    profile_context_state = None
    with dependencies.state.transaction(
        thread_id, operation="prompt_submit", turn_id=turn_id
    ) as slot:
        prior = slot.load()
        Lifecycle.require_submission(slot, expected_submission)
        if prior is not None and prior["phase"] == "submitted":
            prior = None
        fresh_session = prior is None or (
            prior["phase"] == "passed" and prior.get("profile_context_turn_id") is None
        )
        if prior is not None and prior["phase"] == "passed":
            if prior["source_turn_id"] == turn_id and expected_submission is None:
                dependencies.audit(thread_id, turn_id, "auto_steer")
                return None
            profile_context_turn_id = prior.get("profile_context_turn_id")
            if profile_context_turn_id is not None:
                profile_context_state = prior
            else:
                Lifecycle.release(slot)
            prior = None
        if prior is not None:
            if prior["phase"] == "attempting":
                return block_prompt(
                    thread_id,
                    turn_id,
                    "queue_outcome_unknown",
                    "Model Fit: исход постановки прежнего запроса в очередь неизвестен; повторная постановка запрещена.",
                    prior["phase"],
                    dependencies=dependencies,
                )
            if prior["phase"] == "rejected":
                if prior["source_turn_id"] == turn_id:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "queue_rejected_same_turn",
                        "Model Fit: технический ход завершился отказом очереди; новое поручение нужно отправить отдельным ходом.",
                        prior["phase"],
                        dependencies=dependencies,
                    )
                Lifecycle.release(slot)
            if prior["phase"] == "ready":
                if prior.get("pending_assessment") is not None or (
                    prompt.strip() != dependencies.presentation.control_prompt
                    and (
                        turn_id != prior["source_turn_id"]
                        or dependencies.input.prompt_digest(prompt)
                        != prior["prompt_digest"]
                    )
                ):
                    pending = prior
                else:
                    Lifecycle.continue_transfer(slot, prior, turn_id)
                    dependencies.audit(thread_id, turn_id, "auto_handoff_continued")
                    return dependencies.presentation.control_context(
                        thread_id, turn_id, prior
                    )
            elif prior["phase"] == "queued":
                if "queued_client_message_id" in prior:
                    return dependencies.presentation.block(
                        "Model Fit: принятое продолжение проверяется командой assess по нативному client identity."
                    )
                if prior.get("replay_turn_id") == turn_id:
                    dependencies.audit(thread_id, turn_id, "auto_steer")
                    return None
                if prior["source_turn_id"] == turn_id:
                    return block_prompt(
                        thread_id,
                        turn_id,
                        "source_turn_already_queued",
                        "Model Fit: технический ход уже поставил запрос в очередь; новое поручение отправь отдельным ходом.",
                        prior["phase"],
                        dependencies=dependencies,
                    )
                if prior.get(
                    "queued_hook_prompt_digest", prior.get("queued_prompt_digest")
                ) == dependencies.input.prompt_digest(prompt):
                    if prior.get("replay_turn_id") not in (None, turn_id):
                        return block_prompt(
                            thread_id,
                            turn_id,
                            "duplicate_replay",
                            "Model Fit: повторное продолжение запроса запрещено.",
                            prior["phase"],
                            dependencies=dependencies,
                        )
                    with dependencies.native(event.working_directory) as app:
                        if prior["queued_submission_id"] in app.queued_ids(thread_id):
                            return block_prompt(
                                thread_id,
                                turn_id,
                                "replay_still_queued",
                                "Model Fit: продолжение ещё находится в очереди.",
                                prior["phase"],
                                dependencies=dependencies,
                            )
                    selected = dependencies.read_context(event)["active_profile"]
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
                            dependencies=dependencies,
                        )
                    Lifecycle.bind_replay(slot, prior, turn_id)
                    return dependencies.presentation.context(
                        dependencies.presentation.replay_context
                    )
                with dependencies.native(event.working_directory) as app:
                    if prior["queued_submission_id"] in app.queued_ids(thread_id):
                        deleted = app.delete(thread_id, prior["queued_submission_id"])
                        if not deleted:
                            return block_prompt(
                                thread_id,
                                turn_id,
                                "prior_replay_starting",
                                "Model Fit: прежний запрос уже запускается; повтори новое поручение после его завершения.",
                                prior["phase"],
                                dependencies=dependencies,
                            )
                    elif not app.replay_finished(thread_id, prior):
                        if prior.get(
                            "replay_turn_id"
                        ) is not None or not app.source_terminal_without_replay(
                            thread_id, prior["source_turn_id"], turn_id
                        ):
                            return block_prompt(
                                thread_id,
                                turn_id,
                                "prior_replay_running",
                                "Model Fit: прежний запрос выполняется; повтори новое поручение после его завершения.",
                                prior["phase"],
                                dependencies=dependencies,
                            )
                        dependencies.audit(
                            thread_id,
                            turn_id,
                            "auto_handoff_cancelled",
                            {
                                "hook_event": "UserPromptSubmit",
                                "reason_code": "terminal_source_without_replay",
                                "state_phase": "queued",
                            },
                        )
                Lifecycle.release(slot)
        handoff_snapshot = slot.load()
    try:
        request = dependencies.read_context(event)
    except dependencies.context_failure as error:
        capability = dependencies.context_reason(error, thread_id)
        if (
            prompt.strip() == dependencies.presentation.control_prompt
            or not fresh_session
            or pending is not None
            or (profile_context_state is not None)
            or (capability is None)
        ):
            raise
        with dependencies.state.transaction(
            thread_id, nonblocking=True, operation="prompt_submit", turn_id=turn_id
        ) as slot:
            current = slot.load()
            if slot.unsafe() or (current is not None and current != handoff_snapshot):
                raise RuntimeError(
                    "Session capability fallback cannot replace handoff state"
                )
            blocked = blocking_recommendation(event, dependencies=dependencies)
            if blocked is not None:
                dependencies.audit(
                    thread_id,
                    turn_id,
                    "auto_capability_blocked_recommendation",
                    {
                        "hook_event": "UserPromptSubmit",
                        "reason_code": "known_blocking_recommendation",
                    },
                )
                return blocked
            Lifecycle.admit(slot, turn_id)
        dependencies.audit(
            thread_id,
            turn_id,
            "auto_session_unavailable",
            {"hook_event": "UserPromptSubmit", "reason_code": capability},
        )
        return dependencies.presentation.warning(
            "Model Fit: контекст этого чата недоступен для проверки; пригодность профиля не установлена, текущий профиль сохранён."
        )
    with dependencies.state.transaction(
        thread_id, nonblocking=True, operation="prompt_submit", turn_id=turn_id
    ) as slot:
        manual_evidence = load_blocking_recommendation(
            thread_id, dependencies=dependencies
        )
        current = slot.load()
        if (
            fresh_session
            and not slot.unsafe()
            and current == handoff_snapshot
            and (current is None or current["phase"] == "submitted")
            and (manual_evidence is not None)
            and (manual_evidence["active_profile"] != request["active_profile"])
        ):
            dependencies.cache.clear(thread_id)
            manual_evidence = None
    if profile_context_turn_id is not None:
        if profile_context_state.get("native_profile") is not None:
            label = "Сохранённый выбор нативного владельца чата для текущей работы:\n"
            if profile_context_turn_id == turn_id:
                clarification = (
                    "При проверке текущего принятого сообщения нативный профиль отличается от профиля предыдущего переноса: сейчас "
                    + str(profile_context_state["native_profile"])
                    + ". Учитывай этот свежий выбор для текущего запроса. Сохраняй его, если в текущем сообщении "
                    "пользователь явно не поручил заново выбрать или сменить профиль. "
                    "Это факт выбора, а не доказательство пригодности или минимальная модель."
                )
            else:
                clarification = (
                    "После постановки предыдущего запроса нативный владелец чата изменил профиль на "
                    + str(profile_context_state["native_profile"])
                    + ". Сохраняй выбранный профиль для той же работы, пока пользователь отдельно не разрешил смену. "
                    "Этот факт не является оценкой пригодности и не устанавливает минимальную модель."
                )
        else:
            label = "Предыдущее уточнение пользователя, после которого перенос был отменён; учитывай его для той же работы:\n"
            with dependencies.native(event.working_directory) as app:
                clarification = dependencies.input.input_text(
                    app.source_input(
                        thread_id, profile_context_turn_id, include_steering=True
                    )
                )
        request["context"] = (
            label + clarification + "\n\n" + request.get("context", "")
        )[:20000]
    if pending is not None:
        if "input" in request:
            with dependencies.native(event.working_directory) as app:
                earlier = app.handoff_input(thread_id, pending)
            request["input"] = (
                earlier
                if turn_id
                in {
                    pending["source_turn_id"],
                    *pending.get("continuation_turn_ids", []),
                }
                else earlier + request["input"]
            )
        request["context"] = (
            "Исходный незавершённый запрос пользователя:\n"
            + pending["prompt"]
            + "\n\n"
            + request.get("context", "")
        )[:20000]
    result = dependencies.assess(request)
    dependencies.audit(
        thread_id,
        turn_id,
        "auto_assessed",
        {
            "hook_event": "UserPromptSubmit",
            "triage_decision": result["decision"],
            **(
                {"reason_code": "evaluator_abstained"}
                if result["decision"] == "unknown"
                else {}
            ),
            "active_model": request["active_profile"]["model"],
            "active_effort": request["active_profile"]["effort"],
            "recommended_model": result.get("recommended_model"),
            "recommended_effort": result.get("recommended_effort"),
            "task_sha256": dependencies.input.prompt_digest(request["task"]),
            "context_sha256": dependencies.input.prompt_digest(
                request.get("context", "")
            ),
            "input_sha256": dependencies.input.input_digest(request["input"])
            if "input" in request
            else None,
            "assessment_generation": str(expected_submission["generation"])
            if expected_submission is not None
            else None,
            "root_session_id": event.session_id or thread_id,
        },
    )
    return apply_assessment(
        event,
        request,
        result,
        pending=pending,
        handoff_snapshot=handoff_snapshot,
        manual_evidence=manual_evidence,
        profile_context_turn_id=profile_context_turn_id,
        profile_context_state=profile_context_state,
        dependencies=dependencies,
        expected_submission=expected_submission,
    )
