class SubmissionUnavailable(ValueError):
    def __init__(self, thread_id: str | None, reason_code: str) -> None:
        super().__init__("No submitted Model Fit input")
        self.thread_id = thread_id
        self.reason_code = reason_code
