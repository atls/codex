from typing import Protocol

from model_fit.assessment.interfaces.request import ProfileAssessmentInput
from model_fit.autoswitch.interfaces.prompt import SubmissionInput


class AssessmentContextReader(Protocol):
    def __call__(self, submission: SubmissionInput, /) -> ProfileAssessmentInput: ...
