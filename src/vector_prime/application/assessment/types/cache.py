from typing import Protocol
from vector_prime.application.assessment.types.request import ProfileAssessmentInput
from vector_prime.application.assessment.types.decision import AssessmentDecision
from vector_prime.application.assessment.types.recommendation import (
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
