"""Validate identifiers used by Model Fit local state and hook events."""

import re
from model_fit.native_input.types.json import JsonValue

SESSION_ID_PATTERN = re.compile("[A-Za-z0-9-]{1,100}")


def executor_thread_id(event: dict[str, JsonValue]) -> str:
    session = event.get("session_id")
    agent = event.get("agent_id")
    if not isinstance(session, str) or not SESSION_ID_PATTERN.fullmatch(session):
        raise ValueError("Invalid hook session identity")
    if agent is None:
        return session
    if not isinstance(agent, str) or not SESSION_ID_PATTERN.fullmatch(agent):
        raise ValueError("Invalid hook agent identity")
    return agent
