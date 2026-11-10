from typing import Protocol
from model_fit.application.assessment.types.request import ProfileAssessmentInput
from model_fit.application.assessment.types.decision import AssessmentDecision
from model_fit.application.assessment.types.recommendation import (
    RecommendationRecord,
)


class ResultCache(Protocol):
    def load(self, thread_id: str) -> RecommendationRecord | None: ...

    def save(
        self,
        thread_id: str,
        request: ProfileAssessmentInput,
        decision: AssessmentDecision,
    ) -> None: ...

    def clear(self, thread_id: str, *, missing_ok: bool = False) -> None: ...
