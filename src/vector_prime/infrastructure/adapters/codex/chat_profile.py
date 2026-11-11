"""Read the authoritative native chat profile without changing it."""

from vector_prime.infrastructure.adapters.codex.history import RPC_TIMEOUT_SECONDS
from vector_prime.infrastructure.adapters.codex.transport.reader import AppServerReader
from vector_prime.application.assessment.decoding import optional_text
from vector_prime.application.submission.decoding import checked_object


def profile(app: AppServerReader, thread_id: str) -> tuple[str | None, str | None]:
    thread = checked_object(
        app.call(
            "thread/read",
            {"threadId": thread_id, "includeTurns": False},
            RPC_TIMEOUT_SECONDS,
        )["thread"]
    )
    return (
        optional_text(thread.get("model")),
        optional_text(thread.get("reasoningEffort")),
    )
