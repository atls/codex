from model_fit.application.assessment.types.decision import AssessmentDecision
from model_fit.application.assessment.types.profile import ActiveProfile
from model_fit.application.assessment.types.work_relation import WorkRelation
from model_fit.application.assessment.helpers.decision import empty_decision


def apply_work_continuity(
    proposed: AssessmentDecision, relation: WorkRelation, active: ActiveProfile
) -> AssessmentDecision:
    if relation is WorkRelation.DISCUSSION:
        return empty_decision(
            active,
            "keep",
            "Discussion or correction of the previous work retains its active model and reasoning effort.",
        )
    if relation is WorkRelation.UNCERTAIN:
        return empty_decision(
            active,
            "unknown",
            "The relation to the previous work is uncertain; the active profile is retained without a new suitability finding.",
        )
    return proposed
