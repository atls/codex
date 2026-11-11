from vector_prime.application.handoff.types.source import HandoffSource
from vector_prime.application.switch.types.state import ProcessSnapshot


def handoff_source(state: ProcessSnapshot) -> HandoffSource:
    return HandoffSource(
        state["source_turn_id"],
        state.get("prompt"),
        tuple(state.get("continuation_turn_ids", [])),
    )
