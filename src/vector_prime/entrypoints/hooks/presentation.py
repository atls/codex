from vector_prime.entrypoints.hooks.types.output import HookOutput
from typing import assert_never

from vector_prime.application.switch.types.disposition import AssessmentPending
from vector_prime.application.switch.types.disposition import BlockedTurn
from vector_prime.application.switch.types.disposition import ContinueWork
from vector_prime.application.switch.types.disposition import ManualRecommendation
from vector_prime.application.switch.types.disposition import PreparedTransfer
from vector_prime.application.switch.types.disposition import QueuePending
from vector_prime.application.switch.types.disposition import TurnDisposition
from vector_prime.application.switch.types.disposition import TurnNotice
from vector_prime.application.assessment.types.result import UnknownAssessment
from vector_prime.application.switch.types.disposition import UnrelatedAnswer
from vector_prime.application.switch.types.disposition import WorkContext

from vector_prime.entrypoints.hooks import instructions, response


class HookPresentation:
    queued_context = staticmethod(instructions.queued_context)
    pending_context = staticmethod(instructions.pending_context)
    replay_context = instructions.REPLAY_CONTEXT
    hook_output = staticmethod(response.hook_output)
    unknown = staticmethod(response.unknown)
    allow_tool = staticmethod(response.allow_tool)
    deny_tool = staticmethod(response.deny_tool)
    control_context = staticmethod(instructions.control_context)

    def block(self, reason: str) -> HookOutput:
        return {"decision": "block", "reason": reason}

    def warning(self, message: str) -> HookOutput:
        return {"systemMessage": message}

    def context(self, context: str) -> HookOutput:
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }

    def with_context(self, output: HookOutput | None, context: str) -> HookOutput:
        return {**(output or {}), **self.context(context)}

    def extend_reason(self, output: HookOutput, text: str) -> None:
        output["reason"] += text


def render_disposition(result: TurnDisposition | None) -> HookOutput | None:
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
