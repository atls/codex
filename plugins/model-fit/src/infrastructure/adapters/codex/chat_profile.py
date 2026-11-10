"""Read the authoritative native chat profile without changing it."""

from model_fit.infrastructure.adapters.codex.history import RPC_TIMEOUT_SECONDS
from model_fit.infrastructure.adapters.codex.transport.reader import AppServerReader
from model_fit.assessment.decoding import optional_text


def profile(app: AppServerReader, thread_id: str) -> tuple[str | None, str | None]:
    thread = app.call(
        "thread/read",
        {"threadId": thread_id, "includeTurns": False},
        RPC_TIMEOUT_SECONDS,
    )["thread"]
    return (
        optional_text(thread.get("model")),
        optional_text(thread.get("reasoningEffort")),
    )
