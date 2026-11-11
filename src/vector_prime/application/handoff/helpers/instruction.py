from vector_prime.application.handoff.types.instruction import TransferInstruction
from vector_prime.application.handoff.types.plan import TransferTarget
from vector_prime.application.switch.types.state import ProcessSnapshot


def transfer_instruction(state: ProcessSnapshot) -> TransferInstruction:
    return TransferInstruction(
        source_turn_id=state["source_turn_id"],
        generation=state.get("assessment_generation"),
        prompt_digest=state["prompt_digest"],
        target=TransferTarget(state["target_model"], state["target_effort"]),
        official_source_url=state["official_source_url"],
        official_guidance=state["official_guidance"],
        task_inference=state["task_inference"],
    )
