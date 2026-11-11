class ContextUnavailable(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__("Native assessment context is unavailable")
        self.reason_code = reason_code
