from vector_prime.application.handoff.exceptions.invalid_handoff import InvalidHandoff
from vector_prime.application.handoff.types.replay import BoundReplay, UnboundReplay
from vector_prime.application.handoff.types.state import QueuedTransfer


def replay_evidence(queued: QueuedTransfer) -> BoundReplay | UnboundReplay:
    if queued.replay_turn_id is not None:
        return BoundReplay(queued.replay_turn_id)
    if queued.earliest_start is None or queued.input_evidence is None:
        raise InvalidHandoff("invalid_state")
    return UnboundReplay(
        queued.source_turn_id, queued.earliest_start, queued.input_evidence
    )
