from __future__ import annotations
from vector_prime.application.switch import lifecycle as switch_lifecycle
from vector_prime.application.assessment.types.request import ProfileAssessmentInput
from vector_prime.application.assessment.types.decision import AssessmentDecision
from vector_prime.application.submission.helpers import content as codec
from vector_prime.application.assessment.types.state import PendingAssessmentRecord
from vector_prime.application.switch.types.disposition import (
    TurnDisposition,
)
from vector_prime.application.switch.disposition import assessment_disposition
from vector_prime.application.submission.types.input import SubmissionInput
from vector_prime.application.assessment.types.cache import (
    ResultCache,
)
from vector_prime.application.switch.types.storage import TransferStateStore

from vector_prime.application.assessment.lifecycle import load_blocking_recommendation


def blocking_recommendation(
    event: SubmissionInput,
    *,
    prompt_hash: str | None = None,
    empty_input: bool | None = None,
    recommendations: ResultCache,
) -> TurnDisposition | None:
    cached = load_blocking_recommendation(
        event.thread_id, recommendations=recommendations
    )
    if cached is None:
        return None
    active = cached["active_profile"]
    output = assessment_disposition(cached["result"])
    unknown_input = (
        not event.text.strip() if empty_input is None else empty_input
    ) or cached["prompt_hash"] == codec.prompt_digest("")
    same_input = cached["prompt_hash"] == (
        prompt_hash or codec.prompt_digest(event.text)
    )
    return (
        output
        if active["model"] == event.active_model and (same_input or unknown_input)
        else None
    )


def retain_manual_recommendation(
    event: SubmissionInput,
    request: ProfileAssessmentInput,
    result: AssessmentDecision,
    output: TurnDisposition,
    *,
    expected_submission: PendingAssessmentRecord | None = None,
    recommendations: ResultCache,
    store: TransferStateStore,
) -> TurnDisposition:
    with store.transaction(
        event.thread_id,
        nonblocking=True,
        operation="prompt_submit",
        turn_id=event.turn_id,
    ) as slot:
        switch_lifecycle.require_submission(slot, expected_submission)
        current = slot.load()
        submitted = (
            current is not None
            and current["phase"] == "submitted"
            and (
                (current.get("pending_assessment") or {}).get("turn_id")
                == event.turn_id
            )
        )
        if (
            current is None
            or submitted
            or (
                current["phase"] == "passed"
                and current["source_turn_id"] == event.turn_id
            )
        ):
            recommendations.save(
                event.thread_id, {**request, "task": event.text}, result
            )
    return output
