from typing import Literal
from typing_extensions import NotRequired, TypedDict
from pydantic import ConfigDict, with_config
from vector_prime.application.assessment.types.decision import AssessmentDecision


@with_config(ConfigDict(extra="forbid"))
class DecisionProvenance(TypedDict):
    decision_origin: Literal[
        "user_choice", "discussion_rule", "evaluator", "uncertain_relation"
    ]
    work_relation: NotRequired[
        Literal["discussion", "execution", "explicit_reselection", "uncertain"]
    ]


class AssessedDecision(AssessmentDecision):
    provenance: DecisionProvenance
