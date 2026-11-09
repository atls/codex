from typing import Any, Protocol

from model_fit.autoswitch.admission.input import ToolAdmissionInput


class TransferTools(Protocol):
    def matches_assessment(self, request: ToolAdmissionInput) -> bool: ...

    def bound_transfer_input(
        self, request: ToolAdmissionInput, state: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    def matches_profile_switch(
        self, request: ToolAdmissionInput, state: dict[str, Any]
    ) -> bool: ...

    def matches_queue(
        self, request: ToolAdmissionInput, state: dict[str, Any]
    ) -> bool: ...

    def matches_transfer(self, request: ToolAdmissionInput) -> bool: ...
