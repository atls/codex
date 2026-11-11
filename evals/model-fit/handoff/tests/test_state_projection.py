from vector_prime.application.handoff.types.state import QueuedTransfer
from vector_prime.infrastructure.adapters.filesystem.state import (
    read_state,
    state_path,
    write_state,
)
from vector_prime.infrastructure.adapters.filesystem.store import FileStore


def test_coordinator_update_preserves_the_complete_queued_record(codex_home):
    path = state_path("thread")
    path.parent.mkdir(parents=True)
    record = {
        "phase": "queued",
        "source_turn_id": "source",
        "target_model": "fixture-model",
        "target_effort": "medium",
        "queued_submission_id": "receipt",
        "queued_client_message_id": "client",
        "queued_input_digest": "accepted-content",
        "assessment_generation": 0,
        "future_extension": {"opaque": True},
    }
    write_state(path, record)
    with FileStore().transaction("thread") as slot:
        snapshot = slot.load()
        assert snapshot is not None
        queued = snapshot["transfer"]
        assert isinstance(queued, QueuedTransfer)
        assert queued.submission_id == "receipt"
        assert "queued_submission_id" not in snapshot
        assert "future_extension" not in snapshot
        snapshot["assessment_decision"] = "keep"
        slot.save_transition(snapshot)
    assert read_state(path) == {**record, "assessment_decision": "keep"}
    write_state(path, {**record, "future_extension": {"opaque": False}})
    latest = FileStore().snapshot("thread")
    assert latest is not None
    assert latest["revision"] != snapshot["revision"]
