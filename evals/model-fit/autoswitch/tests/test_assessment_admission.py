import pytest
from unittest.mock import MagicMock

from vector_prime.entrypoints.hooks import instructions, operations


@pytest.mark.parametrize("decision", ["keep", "unknown"])
def test_assessment_admission_preserves_decision_and_allows_ordinary_tools(
    decision, codex_home, monkeypatch
):
    monkeypatch.setenv("CODEX_THREAD_ID", "test-thread")
    profile = {"model": "gpt-6-luna", "effort": "low", "speed": None}
    event = {
        "session_id": "test-thread",
        "turn_id": "test-turn",
        "cwd": str(codex_home),
        "model": profile["model"],
        "prompt": "Design a snapshot search engine",
    }
    request = {"task": event["prompt"], "active_profile": profile}
    assert operations.submit_prompt(event) == instructions.pending_context()

    def call(method, params, timeout):
        if method == "thread/read":
            return {
                "thread": {
                    "model": profile["model"],
                    "reasoningEffort": profile["effort"],
                }
            }
        assert method == "thread/items/list"
        return {
            "data": [
                {
                    "item": {
                        "type": "userMessage",
                        "id": "native-message",
                        "content": [{"type": "text", "text": event["prompt"]}],
                    }
                }
            ],
            "nextCursor": None,
        }

    reader = MagicMock()
    reader.__enter__.return_value.call.side_effect = call
    output = operations.assess_submitted(
        context_reader=lambda _: request,
        assessor=lambda _: {"decision": decision},
        native_factory=lambda _: reader,
    )
    if decision == "keep":
        assert (
            "already assessed"
            in output["hookSpecificOutput"]["additionalContext"].casefold()
        )
    else:
        assert "hookSpecificOutput" not in output
        assert "continue the original task" in output["systemMessage"].casefold()
    assert (
        operations.guard_tool(
            {**event, "tool_name": "Bash", "tool_input": {"command": "pwd"}}
        )
        is None
    )
