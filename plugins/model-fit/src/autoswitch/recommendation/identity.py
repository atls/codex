import hashlib
import json

from model_fit.assessment.types.request import ProfileAssessmentInput


def assessment_hash(request: ProfileAssessmentInput) -> str:
    encoded = json.dumps(request, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()
