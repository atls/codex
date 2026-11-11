from vector_prime.application.handoff.guards.queue import (
    queue_preparation,
    require_rejection_state,
)
from vector_prime.application.switch.helpers.transfer import handoff_source
from vector_prime.application.handoff.types.progress import (
    AttemptedHandoff,
    AcceptedHandoff,
)
from vector_prime.application.handoff.types.queue import (
    PreparedQueue,
    QueueCandidate,
    QueueConfirmation,
)
from vector_prime.application.switch.types.state import ProcessSnapshot
from vector_prime.infrastructure.adapters.filesystem.handoff import transfer_state
from vector_prime.application.switch.types.storage import TransferStateSlot


class FileQueueSlot:
    def __init__(self, slot: TransferStateSlot) -> None:
        self.slot = slot
        self.state = slot.load()

    def prepare(self, turn_id: str, now: float) -> PreparedQueue | QueueConfirmation:
        current = self.state
        candidate = (
            QueueCandidate(
                current["source_turn_id"],
                current.get("pending_assessment") is not None,
                transfer_state(current),
            )
            if current is not None
            else None
        )
        result = queue_preparation(candidate, turn_id, now)
        if isinstance(result, QueueConfirmation):
            return result
        return PreparedQueue(result, handoff_source(self._snapshot()))

    def write_attempt(
        self, attempt: AttemptedHandoff, prompt_digest: str, hook_prompt_digest: str
    ) -> None:
        state = self._snapshot()
        state["queued_client_message_id"] = attempt.client_message_id
        state.pop("prompt")
        state["source_input_digest"] = attempt.input_evidence.digest
        state["queued_input_digest"] = attempt.input_evidence.digest
        state["queued_prompt_digest"] = prompt_digest
        state["queued_hook_prompt_digest"] = hook_prompt_digest
        state["phase"] = "attempting"
        self.slot.save_transition(state)

    def write_receipt_id(self, submission_id: str) -> None:
        state = self._snapshot()
        state["queued_submission_id"] = submission_id
        self.slot.save_transition(state)

    def write_accepted_digest(self, digest: str) -> None:
        state = self._snapshot()
        state["queued_input_digest"] = digest
        self.slot.save_transition(state)

    def confirm(self, accepted: AcceptedHandoff, queued_at: int) -> None:
        state = self._snapshot()
        state["queued_submission_id"] = accepted.submission_id
        state["queued_input_digest"] = accepted.input_evidence.digest
        state["phase"] = "queued"
        state["queued_at"] = queued_at
        self.slot.save_transition(state)

    def reject(self) -> None:
        state = self._snapshot()
        require_rejection_state(transfer_state(state))
        state["phase"] = "rejected"
        self.slot.save_transition(state)

    def _snapshot(self) -> ProcessSnapshot:
        if self.state is None:
            raise RuntimeError("Missing handoff snapshot")
        return self.state
