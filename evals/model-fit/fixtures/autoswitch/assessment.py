"""Compose direct assessment stages for state/reconciliation regression fixtures."""

import time

from vector_prime.entrypoints.hooks import operations as api
from vector_prime.entrypoints.hooks.input import assessment_source, prompt_input
from vector_prime.entrypoints.hooks.delivery import deliver_disposition
from vector_prime.application.switch.handlers.processing import evaluate
from vector_prime.infrastructure.adapters.filesystem.audit import record_audit
from vector_prime.infrastructure.adapters.filesystem.cache import (
    Assessment,
)
from vector_prime.infrastructure.adapters.filesystem.store import FileStore


def evaluate_request(event, *, context_reader=None, assessor=None, native_factory=None):
    result = evaluate(
        prompt_input(event),
        assessor=assessor or api.triage,
        audit=record_audit,
        recommendations=Assessment(),
        clock=time.time,
        conversation=api.native_conversation(native_factory),
        read_context=lambda request: (context_reader or api.session_input)(
            assessment_source(request)
        ),
        store=FileStore(),
    )
    return deliver_disposition(result, store=FileStore(), audit=record_audit)
