from dataclasses import dataclass

from model_fit.application.assessment.types.request import ProfileAssessmentInput
from model_fit.application.assessment.types.state import PendingAssessmentRecord


@dataclass(frozen=True)
class Reassessment:
    submission: PendingAssessmentRecord
    request: ProfileAssessmentInput
