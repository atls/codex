from model_fit.autoswitch.state.types.record import HandoffStateRecord
from typing import Protocol
from model_fit.native_input.types.json import JsonValue

from model_fit.autoswitch.admission.types.input import ToolAdmissionInput


class TransferTools(Protocol):
    def matches_assessment(self, request: ToolAdmissionInput) -> bool: ...

    def bound_transfer_input(
        self, request: ToolAdmissionInput, state: HandoffStateRecord
    ) -> dict[str, JsonValue] | None: ...

    def matches_profile_switch(
        self, request: ToolAdmissionInput, state: HandoffStateRecord
    ) -> bool: ...

    def matches_queue(
        self, request: ToolAdmissionInput, state: HandoffStateRecord
    ) -> bool: ...

    def matches_transfer(self, request: ToolAdmissionInput) -> bool: ...
