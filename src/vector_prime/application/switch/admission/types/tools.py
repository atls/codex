from vector_prime.application.switch.types.state import ProcessSnapshot
from typing import Protocol
from vector_prime.application.submission.types.json import JsonValue

from vector_prime.application.switch.admission.types.input import ToolAdmissionInput


class TransferTools(Protocol):
    def matches_assessment(self, request: ToolAdmissionInput) -> bool: ...

    def bound_transfer_input(
        self, request: ToolAdmissionInput, state: ProcessSnapshot
    ) -> dict[str, JsonValue] | None: ...

    def matches_profile_switch(
        self, request: ToolAdmissionInput, state: ProcessSnapshot
    ) -> bool: ...

    def matches_queue(
        self, request: ToolAdmissionInput, state: ProcessSnapshot
    ) -> bool: ...

    def matches_transfer(self, request: ToolAdmissionInput) -> bool: ...
