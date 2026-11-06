from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .dependencies import Dependencies
from .failures.superseded import AssessmentSuperseded
from .failures.unavailable import SubmissionUnavailable
from .lifecycle import Lifecycle
from .recommendation import blocking_recommendation
from .requests.prompt import Prompt


def submit(event: Prompt, *, dependencies: Dependencies) -> dict[str, Any] | None:
    dependencies.audit(
        event.thread_id,
        event.turn_id,
        "auto_started",
        {
            "hook_event": "UserPromptSubmit",
            "root_session_id": event.session_id or event.thread_id,
            "agent_id": event.thread_id
            if event.session_id and event.session_id != event.thread_id
            else None,
        },
    )
    with dependencies.state.transaction(
        event.thread_id, operation="prompt_submit", turn_id=event.turn_id
    ) as slot:
        state = slot.load()
        if slot.unsafe():
            raise ValueError("Unsafe Model Fit state")
        if event.text.strip() == dependencies.presentation.control_prompt:
            if state is not None and state["phase"] == "queued":
                Lifecycle.continue_transfer(slot, state, event.turn_id)
                return dependencies.presentation.queued_context()
            if (
                state is not None
                and state["phase"] == "ready"
                and not state.get("pending_assessment")
            ):
                Lifecycle.continue_transfer(slot, state, event.turn_id)
                dependencies.audit(
                    event.thread_id, event.turn_id, "auto_handoff_continued"
                )
                return dependencies.presentation.control_context(
                    event.thread_id, event.turn_id, state
                )
            return dependencies.presentation.block(
                "Model Fit: служебный перенос не подготовлен либо новый ввод ещё ожидает оценки."
            )
        immediate = state is not None and (
            state["phase"] == "attempting"
            or state["phase"] == "rejected"
            and state["source_turn_id"] == event.turn_id
        )
        if not immediate:
            if state is not None and state["phase"] == "rejected":
                Lifecycle.release(slot)
            Lifecycle.register_submission(
                slot, event, dependencies.input.prompt_digest(event.text)
            )
    if immediate:
        return Lifecycle(dependencies).prepare(event)
    dependencies.audit(
        event.thread_id,
        event.turn_id,
        "auto_deferred",
        {"hook_event": "UserPromptSubmit"},
    )
    return dependencies.presentation.pending_context()


def assess_submitted(
    decode: Callable[[dict[str, Any], str], Prompt], *, dependencies: Dependencies
) -> dict[str, Any]:
    thread_id = dependencies.caller_thread
    if not thread_id:
        raise SubmissionUnavailable(None, "native_thread_required")
    with dependencies.state.transaction(thread_id, operation="assessment") as slot:
        state = slot.load()
        if state is None:
            raise SubmissionUnavailable(thread_id, "submission_missing")
        pending = state.get("pending_assessment")
        if pending is None:
            if state["phase"] == "ready":
                return dependencies.presentation.control_context(
                    thread_id, state["source_turn_id"], state
                )
            if state["phase"] == "queued":
                if state.get("replay_turn_id") is not None:
                    return dependencies.presentation.context(
                        dependencies.presentation.replay_context
                    )
                return dependencies.presentation.queued_context()
            if state.get("assessment_decision") == "keep":
                return dependencies.presentation.assessed()
            return dependencies.presentation.warning(
                "Model Fit: новой проверки не выполнялось; пригодность не установлена."
            )
        if pending["status"] == "running":
            return dependencies.presentation.warning(
                "Model Fit: проверка уже выполняется; дождись результата первого вызова."
            )
        pending = Lifecycle.start_assessment(slot)
    event = decode(pending, "")
    if event.thread_id != thread_id:
        raise ValueError("Submitted input belongs to another Codex thread")
    try:
        try:
            request = dependencies.read_context(event)
        except dependencies.context_failure as error:
            capability = dependencies.context_reason(error, thread_id)
            if (
                capability is None
                or state["phase"] not in {"submitted", "passed"}
                or state.get("profile_context_turn_id") is not None
            ):
                raise
            with dependencies.state.transaction(
                thread_id,
                nonblocking=True,
                operation="assessment",
                turn_id=event.turn_id,
            ) as slot:
                current = slot.load()
                Lifecycle.require_submission(slot, pending)
                blocked = blocking_recommendation(
                    event,
                    dependencies=dependencies,
                    prompt_hash=pending["prompt_hash"],
                    empty_input=pending["empty_text"],
                )
                if blocked is not None:
                    dependencies.cache.clear(thread_id)
                Lifecycle.admit(slot, event.turn_id, "unknown")
                Lifecycle.finish_assessment(slot, pending)
            dependencies.audit(
                thread_id,
                event.turn_id,
                "auto_session_unavailable",
                {"hook_event": "assessment", "reason_code": capability},
            )
            dependencies.audit(
                thread_id, event.turn_id, "auto_unknown", {"hook_event": "assessment"}
            )
            return dependencies.presentation.unknown(
                "Нативный контекст чата недоступен для оценки."
            )
        else:
            with dependencies.native(event.working_directory) as app:
                accepted = app.accepted_input(thread_id, event.turn_id)
                queued = (
                    app.queued_ids(thread_id) if state["phase"] == "queued" else set()
                )
            event = decode(
                pending, dependencies.input.hook_prompt(accepted.source_content)
            )
            request = {
                **request,
                "task": dependencies.input.hook_prompt(accepted.content)
                or request["task"],
            }
            if (
                state["phase"] == "passed"
                and state.get("assessed_profile") is not None
                and state["assessed_profile"] != request["active_profile"]
            ):
                with dependencies.state.transaction(
                    thread_id, operation="assessment", turn_id=event.turn_id
                ) as slot:
                    Lifecycle.require_submission(slot, pending)
                    Lifecycle.admit(
                        slot,
                        event.turn_id,
                        "native_override",
                        event.turn_id,
                        native_profile=request["active_profile"],
                    )
                dependencies.audit(
                    thread_id,
                    event.turn_id,
                    "auto_native_profile_override",
                    {
                        "hook_event": "assessment",
                        "reason_code": "native_choice_after_keep",
                    },
                )
            if state["phase"] == "queued":
                matches = accepted.client_message_id == state.get(
                    "queued_client_message_id", state["source_turn_id"]
                )
                with dependencies.state.transaction(
                    thread_id, operation="assessment", turn_id=event.turn_id
                ) as slot:
                    current = slot.load()
                    Lifecycle.require_submission(slot, pending)
                    if state["queued_submission_id"] in queued:
                        raise RuntimeError("Previous native submission is still queued")
                    unchanged = dependencies.input.input_digest(
                        accepted.content
                    ) == state.get("queued_input_digest")
                    if matches and (
                        request["active_profile"]["model"],
                        request["active_profile"]["effort"],
                    ) != (state["target_model"], state["target_effort"]):
                        Lifecycle.consume_submission(slot, event.turn_id, pending)
                        Lifecycle.admit(
                            slot,
                            event.turn_id,
                            "native_override",
                            event.turn_id,
                            native_profile=request["active_profile"],
                        )
                        Lifecycle.finish_assessment(slot, pending)
                        dependencies.audit(
                            thread_id, event.turn_id, "auto_native_profile_override"
                        )
                        return dependencies.presentation.context(
                            "Model Fit: профиль был изменён нативным владельцем после постановки запроса. Текущий профиль сохранён; его пригодность здесь не переоценивалась. Выполни текущий исходный запрос со всеми текущими вложениями и аннотациями."
                        )
                    if matches and unchanged:
                        Lifecycle.bind_replay(slot, current, event.turn_id)
                        dependencies.audit(thread_id, event.turn_id, "auto_replay")
                        return dependencies.presentation.context(
                            dependencies.presentation.replay_context
                        )
                    Lifecycle.consume_submission(slot, event.turn_id, pending)
                    if not matches and (
                        request["active_profile"]["model"],
                        request["active_profile"]["effort"],
                    ) != (state["target_model"], state["target_effort"]):
                        Lifecycle.admit(
                            slot,
                            event.turn_id,
                            "native_override",
                            event.turn_id,
                            native_profile=request["active_profile"],
                        )
                        dependencies.audit(
                            thread_id,
                            event.turn_id,
                            "auto_native_profile_override",
                            {
                                "hook_event": "assessment",
                                "reason_code": "native_choice_before_new_message",
                            },
                        )
                dependencies.audit(
                    thread_id,
                    event.turn_id,
                    "auto_native_input_changed"
                    if matches
                    else "auto_native_queue_detached",
                )
            request = {**request, "input": accepted.content}
            contextual = replace(dependencies, read_context=lambda _: request)
            output = Lifecycle(contextual).prepare(event, expected_submission=pending)
            with dependencies.native(event.working_directory) as app:
                current_model, current_effort = app.profile(thread_id)
            if not isinstance(current_model, str) or not isinstance(
                current_effort, str
            ):
                raise ValueError("Native profile unavailable after assessment")
            if (current_model, current_effort) != (
                request["active_profile"]["model"],
                request["active_profile"]["effort"],
            ):
                selected = {
                    **request["active_profile"],
                    "model": current_model,
                    "effort": current_effort,
                }
                with dependencies.state.transaction(
                    thread_id, operation="assessment", turn_id=event.turn_id
                ) as slot:
                    current = slot.load()
                    if (
                        current is None
                        or current.get("assessment_generation") != pending["generation"]
                    ):
                        raise AssessmentSuperseded(
                            thread_id, event.turn_id, pending["generation"]
                        )
                    if current["phase"] not in {"ready", "passed", "submitted"}:
                        raise RuntimeError(
                            "Native choice cannot discard unresolved transfer"
                        )
                    cached = dependencies.cache.load(thread_id)
                    if (
                        cached is not None
                        and cached["active_profile"] == request["active_profile"]
                        and cached["prompt_hash"]
                        == dependencies.input.prompt_digest(event.text)
                    ):
                        dependencies.cache.clear(thread_id)
                    Lifecycle.admit(
                        slot,
                        event.turn_id,
                        "native_override",
                        event.turn_id,
                        native_profile=selected,
                    )
                    Lifecycle.finish_assessment(
                        slot, pending, assessed_profile=selected
                    )
                dependencies.audit(
                    thread_id,
                    event.turn_id,
                    "auto_native_profile_override",
                    {
                        "hook_event": "assessment",
                        "reason_code": "native_choice_during_assessment",
                    },
                )
                return dependencies.presentation.context(
                    "Model Fit: нативный владелец изменил профиль во время оценки. Прежняя рекомендация отменена, текущий выбор сохранён; его пригодность не установлена. Выполни исходный запрос с текущими вложениями."
                )
        with dependencies.state.transaction(
            thread_id, operation="assessment", turn_id=event.turn_id
        ) as slot:
            current = slot.load()
            if (
                current is None
                or current.get("assessment_generation") != pending["generation"]
            ):
                raise AssessmentSuperseded(
                    thread_id, event.turn_id, pending["generation"]
                )
            if output is not None and dependencies.presentation.is_block(output):
                Lifecycle.fail_assessment(slot, pending)
            else:
                Lifecycle.finish_assessment(
                    slot, pending, assessed_profile=request["active_profile"]
                )
        dependencies.audit(
            thread_id,
            event.turn_id,
            dependencies.presentation.prompt_outcome(output),
            {
                "hook_event": "assessment",
                "assessment_generation": str(pending["generation"]),
                "root_session_id": event.session_id or thread_id,
            },
        )
        return output if output is not None else dependencies.presentation.assessed()
    except AssessmentSuperseded:
        raise
    except Exception as error:
        if isinstance(error, dependencies.assessment_failure):
            try:
                with dependencies.state.transaction(
                    thread_id,
                    nonblocking=True,
                    operation="assessment",
                    turn_id=event.turn_id,
                ) as slot:
                    continued = Lifecycle.abstain_assessment(slot, pending)
            except BlockingIOError:
                continued = False
            if continued:
                dependencies.audit(
                    thread_id,
                    event.turn_id,
                    "auto_assessment_error:" + type(error).__name__,
                    {
                        "hook_event": "assessment",
                        "reason_code": "assessment_failed_continue",
                        "assessment_generation": pending["generation"],
                    },
                    error=error,
                )
                dependencies.audit(
                    thread_id,
                    event.turn_id,
                    "auto_unknown",
                    {
                        "hook_event": "assessment",
                        "reason_code": "assessment_failed_continue",
                    },
                )
                return dependencies.presentation.unknown(
                    "Оценщик недоступен (" + type(error).__name__ + ")."
                )
        try:
            with dependencies.state.transaction(
                thread_id,
                nonblocking=True,
                operation="assessment",
                turn_id=event.turn_id,
            ) as slot:
                Lifecycle.fail_assessment(slot, pending, reason="assessment_failed")
        except BlockingIOError:
            pass
        raise


def reassess(
    requirements: str, decode, *, dependencies: Dependencies
) -> dict[str, Any]:
    if not isinstance(requirements, str) or not requirements.strip():
        raise ValueError("Changed requirements must be nonempty")
    thread_id = dependencies.caller_thread
    if not thread_id:
        raise SubmissionUnavailable(None, "native_thread_required")
    snapshot = dependencies.state.snapshot(thread_id)
    if (
        snapshot is None
        or snapshot.get("pending_assessment")
        or snapshot["phase"] not in {"passed", "queued"}
    ):
        raise SubmissionUnavailable(thread_id, "reassessment_not_admitted")
    turn_id = (
        snapshot.get("replay_turn_id")
        if snapshot["phase"] == "queued"
        else snapshot["source_turn_id"]
    )
    if not turn_id:
        raise SubmissionUnavailable(thread_id, "reassessment_not_admitted")
    cwd = dependencies.working_directory()
    with dependencies.native(cwd) as app:
        if app.latest_turn_id(thread_id) != turn_id:
            raise SubmissionUnavailable(thread_id, "reassessment_turn_changed")
        if snapshot["phase"] == "queued" and snapshot[
            "queued_submission_id"
        ] in app.queued_ids(thread_id):
            raise SubmissionUnavailable(thread_id, "reassessment_queue_pending")
        accepted = app.accepted_input(thread_id, turn_id)
        model, effort = app.profile(thread_id)
        parent_id = app.parent_thread_id(thread_id)
    source = dependencies.input.hook_prompt(accepted.source_content)
    event = Prompt(
        thread_id,
        turn_id,
        source,
        cwd,
        model,
        {
            "session_id": parent_id or thread_id,
            "agent_id": thread_id if parent_id else None,
            "turn_id": turn_id,
            "cwd": cwd,
            "model": model,
            "prompt": source,
        },
        parent_id or thread_id,
    )
    request = dependencies.read_context(event)
    request = {
        **request,
        "active_profile": {
            "model": model,
            "effort": effort,
            "speed": request["active_profile"].get("speed"),
        },
        "context": "Новые требования, обнаруженные исполнителем после чтения источников (не новое сообщение пользователя):\n"
        + requirements
        + "\n\n"
        + (request.get("context") or ""),
    }
    with dependencies.state.transaction(
        thread_id, operation="reassessment", turn_id=turn_id
    ) as slot:
        if slot.load() != snapshot:
            raise SubmissionUnavailable(thread_id, "reassessment_turn_changed")
        Lifecycle.register_submission(
            slot, event, dependencies.input.prompt_digest(source)
        )
        if snapshot["phase"] == "queued":
            Lifecycle.consume_submission(
                slot, turn_id, slot.load()["pending_assessment"]
            )
            if (model, effort) != (snapshot["target_model"], snapshot["target_effort"]):
                Lifecycle.admit(
                    slot,
                    turn_id,
                    "native_override",
                    turn_id,
                    native_profile=request["active_profile"],
                )
    contextual = replace(dependencies, read_context=lambda _: request)
    return Lifecycle(contextual).assess_submitted(decode)
