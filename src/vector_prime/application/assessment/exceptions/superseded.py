class AssessmentSuperseded(RuntimeError):
    def __init__(
        self, thread_id: str, turn_id: str, generation: str | int | None = None
    ) -> None:
        super().__init__("Submitted input was superseded")
        self.thread_id = thread_id
        self.turn_id = turn_id
        self.generation = str(generation) if generation is not None else None
