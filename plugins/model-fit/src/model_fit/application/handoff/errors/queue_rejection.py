from dataclasses import dataclass


@dataclass(frozen=True)
class NativeQueueRejection:
    error: RuntimeError
