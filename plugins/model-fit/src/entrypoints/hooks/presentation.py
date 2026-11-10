from typing import Any
from typing import assert_never

from model_fit.native_input.types.json import JsonValue
from model_fit.autoswitch.types.disposition import (
    AssessmentPending,
    BlockedTurn,
    ContinueWork,
    ManualRecommendation,
    PreparedTransfer,
    QueuePending,
    TurnDisposition,
    TurnNotice,
    UnknownAssessment,
    UnrelatedAnswer,
    WorkContext,
)

from model_fit.autoswitch.handoff.control_message import CONTROL_PROMPT, CONTROL_PROMPTS
from model_fit.entrypoints.hooks import instructions, response


class HookPresentation:
    queued_context = staticmethod(instructions.queued_context)
    pending_context = staticmethod(instructions.pending_context)
    control_prompt = CONTROL_PROMPT
    control_prompts: tuple[str, ...] = CONTROL_PROMPTS
    replay_context = instructions.REPLAY_CONTEXT
    handoff_cancelled_context = instructions.HANDOFF_CANCELLED_CONTEXT
    replay_stop_reason = instructions.REPLAY_STOP_REASON
    hook_output = staticmethod(response.hook_output)
    unknown = staticmethod(response.unknown)
    allow_tool = staticmethod(response.allow_tool)
    deny_tool = staticmethod(response.deny_tool)
    control_context = staticmethod(instructions.control_context)
    queue_command = staticmethod(instructions.queue_command)

    def block(self, reason: str) -> dict[str, Any]:
        return {"decision": "block", "reason": reason}

    def warning(self, message: str) -> dict[str, Any]:
        return {"systemMessage": message}

    def context(self, context: str) -> dict[str, Any]:
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }

    def with_context(
        self, output: dict[str, Any] | None, context: str
    ) -> dict[str, Any]:
        return {**(output or {}), **self.context(context)}

    def extend_reason(self, output: dict[str, Any], text: str) -> None:
        output["reason"] += text

    def is_block(self, output: dict[str, Any]) -> bool:
        return output.get("decision") == "block"

    def assessed(self) -> dict[str, Any]:
        return self.context(instructions.ASSESSED_CONTEXT)

    def prompt_outcome(self, output: dict[str, Any] | None) -> str:
        if output is None:
            return "auto_pass"
        context = output.get("hookSpecificOutput", {}).get("additionalContext")
        if context == self.handoff_cancelled_context:
            return "auto_unknown" if "systemMessage" in output else "auto_pass"
        if context == self.replay_context:
            return "auto_replay"
        if "hookSpecificOutput" in output:
            return "auto_handoff"
        return "auto_block" if output.get("decision") == "block" else "auto_unknown"


def render_disposition(result: TurnDisposition | None) -> dict[str, JsonValue] | None:
    if result is None:
        return None
    renderer = HookPresentation()
    match result:
        case BlockedTurn(reason):
            return renderer.block(reason)
        case TurnNotice(message):
            return renderer.warning(message)
        case UnknownAssessment(message):
            return renderer.unknown(message)
        case ManualRecommendation(evidence, explanation):
            output = renderer.hook_output(evidence)
            if output is None:
                raise ValueError("Recommendation evidence has no presentation")
            renderer.extend_reason(output, explanation)
            return output
        case ContinueWork(context, preceding):
            contexts = {
                WorkContext.ASSESSED: instructions.ASSESSED_CONTEXT,
                WorkContext.REPLAY: instructions.REPLAY_CONTEXT,
                WorkContext.TRANSFER_CANCELLED: instructions.HANDOFF_CANCELLED_CONTEXT,
            }
            text = context if isinstance(context, str) else contexts[context]
            return renderer.with_context(render_disposition(preceding), text)
        case AssessmentPending():
            return renderer.pending_context()
        case QueuePending():
            return renderer.queued_context()
        case PreparedTransfer(thread_id, turn_id, state):
            return renderer.control_context(thread_id, turn_id, state)
        case UnrelatedAnswer():
            return renderer.block(instructions.REPLAY_STOP_REASON)
        case _:
            assert_never(result)
