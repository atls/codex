from model_fit.application.handoff.types.queue_receipt import NativeQueueReceipt
from model_fit.application.submission.types.json import JsonValue


def accepted_content(receipt: NativeQueueReceipt) -> list[dict[str, JsonValue]]:
    if not receipt.accepted_input:
        raise ValueError("Native queue receipt input is unavailable")
    return receipt.accepted_input


def require_receipt_identity(receipt: NativeQueueReceipt) -> None:
    if not receipt.submission_id:
        raise RuntimeError("Queue confirmation requires its native receipt")
