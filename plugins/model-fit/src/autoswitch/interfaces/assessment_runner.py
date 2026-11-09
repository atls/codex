from typing import Protocol

from model_fit.assessment.interfaces.decision import AssessmentDecision
from model_fit.assessment.interfaces.request import ProfileAssessmentInput


class AssessmentRunner(Protocol):
    def __call__(self, request: ProfileAssessmentInput, /) -> AssessmentDecision: ...
