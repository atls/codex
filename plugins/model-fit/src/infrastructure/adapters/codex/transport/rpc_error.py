from model_fit.native_input.types.json import JsonValue


class AppServerRPCError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        method: str | None = None,
        code: JsonValue = None,
        thread_id: JsonValue = None,
    ) -> None:
        super().__init__(f"{method}: {message}" if method else message)
        self.method = method
        self.code = code
        self.rpc_message = message
        self.thread_id = thread_id
