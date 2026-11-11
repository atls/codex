class QueueRejected(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Codex rejected the native queue submission")
