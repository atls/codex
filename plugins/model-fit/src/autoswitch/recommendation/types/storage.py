from typing import Protocol
from model_fit.assessment.types.request import ProfileAssessmentInput
from model_fit.assessment.types.decision import AssessmentDecision
from model_fit.autoswitch.recommendation.types.record import RecommendationRecord


class RecommendationStore(Protocol):
    def load(self, thread_id: str) -> RecommendationRecord | None: ...

    def save(
        self,
        thread_id: str,
        request: ProfileAssessmentInput,
        decision: AssessmentDecision,
    ) -> None: ...

    def clear(self, thread_id: str, *, missing_ok: bool = False) -> None: ...

    def unsafe(self, thread_id: str) -> bool: ...
