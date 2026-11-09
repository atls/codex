from typing import Protocol
from model_fit.assessment.types.typed_dicts.decision import AssessmentDecision
from model_fit.assessment.types.typed_dicts.request import ProfileAssessmentInput
from model_fit.submission.types.dataclasses.input import SubmissionInput


class AssessmentContextReader(Protocol):
    def __call__(self, submission: SubmissionInput, /) -> ProfileAssessmentInput: ...


class AssessmentRunner(Protocol):
    def __call__(self, request: ProfileAssessmentInput, /) -> AssessmentDecision: ...
