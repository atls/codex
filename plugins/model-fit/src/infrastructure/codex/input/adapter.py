import model_fit.infrastructure.codex.input.codec as input


class NativeInputs:
    prompt_digest = staticmethod(input.prompt_digest)
    input_digest = staticmethod(input.input_digest)
    input_text = staticmethod(input.input_text)
    hook_prompt = staticmethod(input.hook_prompt)
