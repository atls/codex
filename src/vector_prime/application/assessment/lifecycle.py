"""Own assessment registration, execution and evaluation progress."""

from __future__ import annotations

from vector_prime.application.assessment.constraints.is_context_within_limit import (
    MAX_CONTEXT_CHARS,
)


from vector_prime.application.assessment.types.result import UnknownAssessment
from vector_prime.application.assessment.helpers.failure import evaluator_failure_name
from vector_prime.application.assessment.types.cache import ResultCache
from vector_prime.application.assessment.types.recommendation import (
    RecommendationRecord,
)
from vector_prime.application.assessment.guards.cache import (
    require_blocking_record,
)
from vector_prime.application.assessment.types.reassessment import Reassessment
from vector_prime.application.assessment.request import require_reassessment
from vector_prime.application.assessment.helpers.context import requirements_context
from vector_prime.application.submission.helpers.content import prompt_digest
from uuid import uuid4
from vector_prime.application.assessment.types.state import PendingAssessmentRecord
from vector_prime.application.assessment.guards.generation import require_waiting
from vector_prime.application.submission.types.input import SubmissionInput


import hashlib
from vector_prime.application.submission.types.json import JsonValue

from vector_prime.application.assessment.types.catalog import ProfileCatalog
from vector_prime.application.assessment.types.profile import ActiveProfile
from vector_prime.application.assessment.types.decision import AssessmentDecision
from vector_prime.application.assessment.types.evaluator import AssessmentEvaluator
from vector_prime.application.assessment.types.request import ProfileAssessmentInput
from vector_prime.application.assessment.types.sources import AssessmentSources
from vector_prime.application.assessment.prompt import assessment_prompt
from vector_prime.application.assessment.types.work_relation import WorkRelation
from vector_prime.application.assessment.guards.catalog import require_profiles
from vector_prime.application.assessment.helpers.diagnostics import record_user_choice
from vector_prime.application.assessment.decoding import decode_evaluation
from vector_prime.application.assessment.helpers.decision import empty_decision
from vector_prime.application.assessment.decision import validate
from vector_prime.application.assessment.request import validated_request


def assess(
    request: ProfileAssessmentInput,
    evaluator_model: str,
    evaluator_effort: str,
    timeout: int,
    source_bundle: tuple[str, ProfileCatalog] | None = None,
    diagnostics: dict[str, JsonValue] | None = None,
    *,
    source_reader: AssessmentSources,
    evaluator: AssessmentEvaluator,
) -> AssessmentDecision:
    task, active, context, prior = validated_request(request)
    if prior is not None:
        record_user_choice(diagnostics, request)
        return empty_decision(
            active,
            "keep",
            "The user already selected the active profile for the same work",
        )
    source_text, models = (
        source_bundle if source_bundle is not None else source_reader()
    )
    require_profiles(
        active,
        {"model": evaluator_model, "effort": evaluator_effort, "speed": None},
        models,
    )
    instructions, prompt = assessment_prompt(task, active, context, source_text)
    if diagnostics is not None:
        diagnostics["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
    if "input" in request:
        output = evaluator(
            instructions,
            prompt,
            evaluator_model,
            evaluator_effort,
            timeout,
            diagnostics,
            native_input=request["input"],
        )
    else:
        output = evaluator(
            instructions,
            prompt,
            evaluator_model,
            evaluator_effort,
            timeout,
            diagnostics,
        )
    relation, proposal = decode_evaluation(output)
    if diagnostics is not None:
        diagnostics["work_relation"] = relation.value
    return complete(proposal, relation, active, models)


def register(event: SubmissionInput, prompt_hash: str) -> PendingAssessmentRecord:
    generation = new_generation()
    pending: PendingAssessmentRecord = {
        "thread_id": event.thread_id,
        "turn_id": event.turn_id,
        "root_session_id": event.session_id or event.thread_id,
        "agent_id": event.thread_id
        if event.session_id and event.session_id != event.thread_id
        else None,
        "working_directory": event.working_directory,
        "active_model": event.active_model,
        "prompt_hash": prompt_hash,
        "empty_text": not event.text.strip(),
        "status": "waiting",
        "generation": generation,
    }
    return pending


def start(pending: PendingAssessmentRecord) -> PendingAssessmentRecord:
    require_waiting(pending)
    pending["status"] = "running"
    return pending


def fail(pending: PendingAssessmentRecord, reason: str | None = None) -> None:
    pending["status"] = "failed"
    if reason is not None:
        pending["failure_reason"] = reason


def complete(
    proposed: object,
    relation: WorkRelation,
    active: ActiveProfile,
    models: ProfileCatalog,
) -> AssessmentDecision:
    decision = validate(proposed, active, models)
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
    return decision


def recover(error: Exception) -> UnknownAssessment | None:
    failure = evaluator_failure_name(error)
    if failure is None:
        return None
    return UnknownAssessment("The evaluator is unavailable (" + failure + ").")


def load_blocking_recommendation(
    thread_id: str, *, recommendations: ResultCache
) -> RecommendationRecord | None:
    cached = recommendations.load(thread_id)
    if cached is not None:
        require_blocking_record(cached)
    return cached


def reassess(
    event: SubmissionInput,
    request: ProfileAssessmentInput,
    requirements: str,
    profile: ActiveProfile,
) -> Reassessment:
    require_reassessment(requirements)
    context = requirements_context(requirements)
    updated: ProfileAssessmentInput = {
        **request,
        "active_profile": profile,
        "context": context
        + (request.get("context") or "")[: MAX_CONTEXT_CHARS - len(context)],
    }
    return Reassessment(register(event, prompt_digest(event.text)), updated)


def new_generation() -> str:
    return uuid4().hex
