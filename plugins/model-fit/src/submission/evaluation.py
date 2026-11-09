from typing import Protocol
from model_fit.assessment.decision import AssessmentDecision
from model_fit.assessment.request import ProfileAssessmentInput
from model_fit.submission.input import SubmissionInput


class AssessmentContextReader(Protocol):
    def __call__(self, submission: SubmissionInput, /) -> ProfileAssessmentInput: ...


class AssessmentRunner(Protocol):
    def __call__(self, request: ProfileAssessmentInput, /) -> AssessmentDecision: ...
