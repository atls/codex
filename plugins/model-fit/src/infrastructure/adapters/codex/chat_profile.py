"""Read the authoritative native chat profile without changing it."""

from model_fit.infrastructure.adapters.codex.history import RPC_TIMEOUT_SECONDS


def profile(app, thread_id):
    thread = app.call(
        "thread/read",
        {"threadId": thread_id, "includeTurns": False},
        RPC_TIMEOUT_SECONDS,
    )["thread"]
    return (thread.get("model"), thread.get("reasoningEffort"))
