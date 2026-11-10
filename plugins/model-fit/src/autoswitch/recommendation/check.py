from __future__ import annotations

from model_fit.autoswitch.lifecycle import submission as submission_lifecycle


from model_fit.assessment.validation import validated_active_profile
from model_fit.assessment.types.profile import ActiveProfile
from model_fit.assessment.types.request import ProfileAssessmentInput
from model_fit.assessment.types.decision import AssessmentDecision
from model_fit.autoswitch.recommendation.validation import require_recommendation
from model_fit.autoswitch.recommendation.types.record import (
    RecommendationRecord,
)
from model_fit.native_input import codec
from model_fit.autoswitch.state.types.record import PendingAssessmentRecord
from model_fit.autoswitch.types.disposition import (
    TurnDisposition,
)
from model_fit.autoswitch.disposition import assessment_disposition

from model_fit.submission.types.input import SubmissionInput
from model_fit.autoswitch.recommendation.types.storage import (
    RecommendationStore,
)
from model_fit.autoswitch.state.types.storage import TransferStateStore


def recommended_profile(pending: RecommendationRecord) -> ActiveProfile:
    active = pending["active_profile"]
    result = pending["result"]
    return {
        "model": result.get("recommended_model") or active["model"],
        "effort": result.get("recommended_effort") or active["effort"],
        "speed": result.get("recommended_speed") or active["speed"],
    }


def load_blocking_recommendation(
    thread_id: str,
    *,
    recommendations: RecommendationStore,
) -> RecommendationRecord | None:
    if recommendations.unsafe(thread_id):
        raise ValueError("Blocking recommendation cannot be a symlink")
    cached = recommendations.load(thread_id)
    if cached is None:
        return None
    if (
        len(cached["prompt_hash"]) != 64
        or len(bytes.fromhex(cached["prompt_hash"])) != 32
        or cached["prompt_hash"] != cached["prompt_hash"].lower()
    ):
        raise ValueError("Blocking recommendation input hash is invalid")
    active = validated_active_profile({"active_profile": cached["active_profile"]})
    if (
        not active["model"]
        or not active["effort"]
        or not {"active_model", "active_effort", "active_speed"}.issubset(
            cached["result"]
        )
        or cached["result"].get("active_model") != active["model"]
        or cached["result"].get("active_effort") != active["effort"]
        or cached["result"].get("active_speed") != active["speed"]
    ):
        raise ValueError("Blocking recommendation profile is inconsistent")
    require_recommendation(cached["result"])
    return cached


def blocking_recommendation(
    event: SubmissionInput,
    *,
    prompt_hash: str | None = None,
    empty_input: bool | None = None,
    recommendations: RecommendationStore,
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
    recommendations: RecommendationStore,
    store: TransferStateStore,
) -> TurnDisposition:
    with store.transaction(
        event.thread_id,
        nonblocking=True,
        operation="prompt_submit",
        turn_id=event.turn_id,
    ) as slot:
        submission_lifecycle.require_submission(slot, expected_submission)
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
