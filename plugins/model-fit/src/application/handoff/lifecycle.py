"""Own transfer commands and every durable transfer transition."""

from typing import Any
from uuid import uuid4

from .dependencies import Dependencies
from .failures.superseded import AssessmentSuperseded
from .ports.state import State
from .requests.answer_check import AnswerCheck
from .requests.prompt import Prompt
from .requests.tool_check import ToolCheck


class Lifecycle:
    def __init__(self, dependencies: Dependencies) -> None:
        self.dependencies = dependencies

    def prepare(
        self, event: Prompt, *, expected_submission: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        from . import preparation

        return preparation.prepare(
            event,
            dependencies=self.dependencies,
            expected_submission=expected_submission,
        )

    def enqueue(self, thread_id: str, turn_id: str) -> dict[str, str]:
        from . import queue

        return queue.enqueue(thread_id, turn_id, dependencies=self.dependencies)

    def check_tool(self, event: ToolCheck) -> dict[str, Any] | None:
        from . import guards

        return guards.guard_tool(event, dependencies=self.dependencies)

    def can_continue_admitted_tool(self, event: ToolCheck) -> bool:
        from . import guards

        return guards.can_continue_admitted_tool(
            event,
            self.dependencies.state.snapshot(event.thread_id),
            dependencies=self.dependencies,
        )

    def finish(self, event: AnswerCheck) -> dict[str, Any] | None:
        from . import guards

        return guards.guard_replay_answer(event, dependencies=self.dependencies)

    def submit(self, event: Prompt) -> dict[str, Any] | None:
        from . import submission

        return submission.submit(event, dependencies=self.dependencies)

    def assess_submitted(self, decode) -> dict[str, Any]:
        from . import submission

        try:
            return submission.assess_submitted(decode, dependencies=self.dependencies)
        except AssessmentSuperseded as error:
            self.dependencies.audit(
                error.thread_id,
                error.turn_id,
                "auto_assessment_superseded",
                {
                    "hook_event": "assessment",
                    "reason_code": "newer_submission",
                    "assessment_generation": error.generation,
                },
            )
            return self.dependencies.presentation.context(
                "Предыдущая оценка Model Fit устарела и не применена. "
                "Используй инструкцию Model Fit для последнего принятого ввода; "
                "не повторяй перенос по результату отменённой оценки."
            )

    def reassess(self, requirements: str, decode) -> dict[str, Any]:
        from . import submission

        return submission.reassess(requirements, decode, dependencies=self.dependencies)

    @staticmethod
    def require_submission(slot: State, expected: dict[str, Any] | None) -> None:
        if expected is None:
            return
        current = slot.load()
        if current is None or current.get("pending_assessment") != expected:
            raise AssessmentSuperseded(
                expected["thread_id"], expected["turn_id"], expected.get("generation")
            )

    @staticmethod
    def _save(slot: State, state: dict[str, Any]) -> None:
        current = slot.load()
        generation = state.get("pending_assessment", {}).get("generation")
        if generation is None and current is not None:
            generation = current.get("pending_assessment", {}).get(
                "generation", current.get("assessment_generation")
            )
        if generation is not None:
            state = {**state, "assessment_generation": generation}
        slot.save(state)

    @staticmethod
    def authorize_transfer(slot: State, state: dict[str, Any], now: float) -> None:
        Lifecycle._save(slot, {**state, "transfer_authorized_at": now})

    @staticmethod
    def register_submission(slot: State, event: Prompt, prompt_hash: str) -> None:
        current = slot.load()
        if (
            slot.unsafe()
            or current is not None
            and current["phase"] in {"attempting", "rejected"}
        ):
            raise RuntimeError(
                "Cannot replace an unresolved transfer with a submission"
            )
        state = current or {"phase": "submitted", "source_turn_id": event.turn_id}
        if state["phase"] == "submitted":
            state["source_turn_id"] = event.turn_id
        generation = uuid4().hex
        state["pending_assessment"] = {
            "thread_id": event.thread_id,
            "turn_id": event.turn_id,
            "root_session_id": event.session_id or event.thread_id,
            "agent_id": event.thread_id
            if event.session_id and event.session_id != event.thread_id
            else None,
            "working_directory": event.working_directory,
            "active_model": event.active_model,
            "prompt_hash": prompt_hash,
            "empty_text": not event.text.strip(),
            "status": "waiting",
            "generation": generation,
        }
        Lifecycle._save(slot, state)

    @staticmethod
    def start_assessment(slot: State) -> dict[str, Any]:
        state = slot.load()
        if state is None or not state.get("pending_assessment"):
            raise ValueError("No submitted Model Fit input")
        if state["pending_assessment"]["status"] != "waiting":
            raise RuntimeError("Submitted Model Fit input is not awaiting assessment")
        state["pending_assessment"]["status"] = "running"
        Lifecycle._save(slot, state)
        return state["pending_assessment"]

    @staticmethod
    def fail_assessment(
        slot: State, pending: dict[str, Any], reason: str | None = None
    ) -> None:
        state = slot.load()
        if state is not None and state.get("pending_assessment") == pending:
            state["pending_assessment"]["status"] = "failed"
            if reason is not None:
                state["pending_assessment"]["failure_reason"] = reason
            Lifecycle._save(slot, state)

    @staticmethod
    def abstain_assessment(slot: State, pending: dict[str, Any]) -> bool:
        state = slot.load()
        if (
            state is None
            or not pending.get("generation")
            or state.get("assessment_generation") != pending["generation"]
            or state.get("pending_assessment") not in (None, pending)
            or state["phase"] not in {"submitted", "passed", "ready"}
        ):
            return False
        Lifecycle.admit(
            slot, pending["turn_id"], "unknown", state.get("profile_context_turn_id")
        )
        Lifecycle.finish_assessment(slot, pending)
        return True

    @staticmethod
    def finish_assessment(
        slot: State,
        pending: dict[str, Any],
        assessed_profile: dict[str, Any] | None = None,
    ) -> None:
        state = slot.load()
        if state is not None and (
            state.get("pending_assessment") == pending
            or (
                state.get("pending_assessment") is None
                and pending.get("generation") is not None
                and state.get("assessment_generation") == pending["generation"]
            )
        ):
            state.pop("pending_assessment", None)
            if state["phase"] == "passed" and assessed_profile is not None:
                state["assessed_profile"] = assessed_profile
            Lifecycle._save(slot, state)

    @staticmethod
    def consume_submission(slot: State, turn_id: str, pending: dict[str, Any]) -> None:
        current = slot.load()
        if (
            current is None
            or current["phase"] != "queued"
            or current.get("pending_assessment") != pending
        ):
            raise RuntimeError("Native queue receipt changed during assessment")
        Lifecycle._save(
            slot,
            {
                "phase": "submitted",
                "source_turn_id": turn_id,
                "pending_assessment": pending,
            },
        )

    @staticmethod
    def admit(
        slot: State,
        turn_id: str,
        decision: str | None = None,
        profile_context_turn_id: str | None = None,
        native_profile: dict[str, Any] | None = None,
        *,
        supersede_assessment: bool = False,
    ) -> None:
        current = slot.load()
        if current is not None and current["phase"] not in {
            "ready",
            "passed",
            "submitted",
        }:
            raise RuntimeError("Admission cannot discard an unresolved queue attempt")
        state = {"phase": "passed", "source_turn_id": turn_id}
        if current is not None and current.get("assessed_profile") is not None:
            state["assessed_profile"] = current["assessed_profile"]
        if (
            current is not None
            and current.get("pending_assessment", {}).get("turn_id") == turn_id
        ):
            state["pending_assessment"] = current["pending_assessment"]
        if decision is not None:
            state["assessment_decision"] = decision
        if profile_context_turn_id is not None:
            state["profile_context_turn_id"] = profile_context_turn_id
            if native_profile is not None:
                state["native_profile"] = native_profile
            elif (
                current is not None
                and current.get("profile_context_turn_id") == profile_context_turn_id
                and current.get("native_profile") is not None
            ):
                state["native_profile"] = current["native_profile"]
        if supersede_assessment:
            state["assessment_generation"] = uuid4().hex
            slot.save(state)
        else:
            Lifecycle._save(slot, state)

    @staticmethod
    def stage(slot: State, state: dict[str, Any]) -> None:
        current = slot.load()
        if current is not None and current["phase"] not in {
            "passed",
            "ready",
            "submitted",
        }:
            raise RuntimeError("Cannot stage a transfer while queue outcome is pending")
        Lifecycle._save(slot, {**state, "phase": "ready"})

    @staticmethod
    def continue_transfer(slot: State, state: dict[str, Any], turn_id: str) -> None:
        if state["phase"] not in {"ready", "queued"}:
            raise RuntimeError("Only a prepared transfer accepts a control turn")
        state["control_turn_id"] = turn_id
        if turn_id != state["source_turn_id"]:
            continuations = state.setdefault("continuation_turn_ids", [])
            if turn_id not in continuations:
                continuations.append(turn_id)
        Lifecycle._save(slot, state)

    @staticmethod
    def bind_replay(slot: State, state: dict[str, Any], turn_id: str) -> None:
        if state["phase"] != "queued" or state.get("replay_turn_id") not in (
            None,
            turn_id,
        ):
            raise RuntimeError("Replay does not belong to this queued transfer")
        state.pop("pending_assessment", None)
        state["replay_turn_id"] = turn_id
        Lifecycle._save(slot, state)

    @staticmethod
    def begin_queue(slot: State, state: dict[str, Any]) -> None:
        if state["phase"] != "ready":
            raise RuntimeError("Only a prepared transfer can enter the queue")
        state["phase"] = "attempting"
        Lifecycle._save(slot, state)

    @staticmethod
    def receipt(slot: State, state: dict[str, Any], submission_id: str) -> None:
        if state["phase"] != "attempting":
            raise RuntimeError("Queue receipt requires an active attempt")
        state["queued_submission_id"] = submission_id
        Lifecycle._save(slot, state)

    @staticmethod
    def reject(slot: State, state: dict[str, Any]) -> None:
        if state["phase"] != "attempting":
            raise RuntimeError("Only an attempted transfer can be rejected")
        state["phase"] = "rejected"
        Lifecycle._save(slot, state)

    @staticmethod
    def confirm_queue(slot: State, state: dict[str, Any], timestamp: float) -> None:
        if state["phase"] != "attempting" or not state.get("queued_submission_id"):
            raise RuntimeError("Queue confirmation requires its native receipt")
        state.update(phase="queued", queued_at=int(timestamp))
        Lifecycle._save(slot, state)

    @staticmethod
    def release(slot: State) -> None:
        current = slot.load()
        if current is not None and current["phase"] == "attempting":
            raise RuntimeError("An unresolved queue attempt cannot be released")
        if current is not None and current.get("pending_assessment"):
            pending = current["pending_assessment"]
            Lifecycle._save(
                slot,
                {
                    "phase": "submitted",
                    "source_turn_id": pending["turn_id"],
                    "pending_assessment": pending,
                },
            )
        else:
            slot.clear()
