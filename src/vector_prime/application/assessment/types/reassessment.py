from dataclasses import dataclass

from vector_prime.application.assessment.types.request import ProfileAssessmentInput
from vector_prime.application.assessment.types.state import PendingAssessmentRecord


@dataclass(frozen=True)
class Reassessment:
    submission: PendingAssessmentRecord
    request: ProfileAssessmentInput
