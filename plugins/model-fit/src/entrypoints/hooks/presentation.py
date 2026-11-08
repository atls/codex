from model_fit.entrypoints.hooks import instructions, response


class HookPresentation:
    queued_context = staticmethod(instructions.queued_context)
    pending_context = staticmethod(instructions.pending_context)
    control_prompt = instructions.CONTROL_PROMPT
    replay_context = instructions.REPLAY_CONTEXT
    handoff_cancelled_context = instructions.HANDOFF_CANCELLED_CONTEXT
    replay_stop_reason = instructions.REPLAY_STOP_REASON
    hook_output = staticmethod(response.hook_output)
    unknown = staticmethod(response.unknown)
    allow_tool = staticmethod(response.allow_tool)
    deny_tool = staticmethod(response.deny_tool)
    control_context = staticmethod(instructions.control_context)
    queue_command = staticmethod(instructions.queue_command)

    def block(self, reason):
        return {"decision": "block", "reason": reason}

    def warning(self, message):
        return {"systemMessage": message}

    def context(self, context):
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }

    def with_context(self, output, context):
        return {**(output or {}), **self.context(context)}

    def extend_reason(self, output, text):
        output["reason"] += text

    def is_block(self, output):
        return output.get("decision") == "block"

    def assessed(self):
        return self.context(instructions.ASSESSED_CONTEXT)

    def prompt_outcome(self, output):
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
