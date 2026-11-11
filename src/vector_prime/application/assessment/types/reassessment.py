from dataclasses import dataclass

from vector_prime.application.assessment.types.request import ProfileAssessmentInput
from vector_prime.application.assessment.types.state import PendingAssessment


@dataclass(frozen=True)
class Reassessment:
    submission: PendingAssessment
    request: ProfileAssessmentInput
