from typing import Protocol
from vector_prime.application.assessment.types.decision import AssessmentDecision
from vector_prime.application.assessment.types.request import ProfileAssessmentInput
from vector_prime.application.submission.types.input import SubmissionInput


class AssessmentContextReader(Protocol):
    def __call__(self, submission: SubmissionInput, /) -> ProfileAssessmentInput: ...


class AssessmentRunner(Protocol):
    def __call__(self, request: ProfileAssessmentInput, /) -> AssessmentDecision: ...
