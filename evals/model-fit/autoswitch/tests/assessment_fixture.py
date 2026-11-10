"""Compose direct assessment stages for state/reconciliation regression fixtures."""

import time

from model_fit.entrypoints.hooks import operations as api
from model_fit.entrypoints.hooks.input import prompt_input
from model_fit.entrypoints.hooks.delivery import deliver_disposition
from model_fit.application.switch.scenarios.evaluate import evaluate
from model_fit.infrastructure.adapters.filesystem.audit import record_audit
from model_fit.infrastructure.adapters.filesystem.assessment_cache import (
    FileAssessmentCache,
)
from model_fit.infrastructure.adapters.filesystem.store import FileStore


def evaluate_request(event, *, context_reader=None, assessor=None, native_factory=None):
    result = evaluate(
        prompt_input(event),
        assessor=assessor or api.triage,
        audit=record_audit,
        recommendations=FileAssessmentCache(),
        clock=time.time,
        conversation=api.native_conversation(native_factory),
        read_context=lambda request: (context_reader or api.session_input)(
            request.source
        ),
        store=FileStore(),
    )
    return deliver_disposition(result, store=FileStore(), audit=record_audit)
