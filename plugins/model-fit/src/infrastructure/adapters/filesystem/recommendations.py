from collections.abc import Callable
from pathlib import Path
from model_fit.assessment.types.request import ProfileAssessmentInput
from model_fit.assessment.types.decision import AssessmentDecision
from model_fit.autoswitch.recommendation.types.record import RecommendationRecord

import model_fit.infrastructure.adapters.filesystem.pending as recommendation


class FileRecommendations:
    def __init__(
        self, path_for_thread: Callable[[str], Path] = recommendation.pending_path
    ) -> None:
        self.path_for_thread = path_for_thread

    def load(self, thread_id: str) -> RecommendationRecord | None:
        return recommendation.load_pending(self.path_for_thread(thread_id))

    def save(
        self,
        thread_id: str,
        request: ProfileAssessmentInput,
        result: AssessmentDecision,
    ) -> None:
        recommendation.save_pending(self.path_for_thread(thread_id), request, result)

    def clear(self, thread_id: str, *, missing_ok: bool = False) -> None:
        self.path_for_thread(thread_id).unlink(missing_ok=missing_ok)

    def unsafe(self, thread_id: str) -> bool:
        return self.path_for_thread(thread_id).is_symlink()
