from typing import Protocol
from model_fit.assessment.types.decision import AssessmentDecision
from model_fit.assessment.types.request import ProfileAssessmentInput
from model_fit.submission.types.input import SubmissionInput


class AssessmentContextReader(Protocol):
    def __call__(self, submission: SubmissionInput, /) -> ProfileAssessmentInput: ...


class AssessmentRunner(Protocol):
    def __call__(self, request: ProfileAssessmentInput, /) -> AssessmentDecision: ...
