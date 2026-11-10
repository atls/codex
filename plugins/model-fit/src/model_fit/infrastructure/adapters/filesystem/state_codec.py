from pydantic import TypeAdapter, ValidationError

from model_fit.application.switch.state.types.record import HandoffStateRecord


LEGACY_STATE = TypeAdapter(HandoffStateRecord)


def decode_state(value: object) -> HandoffStateRecord:
    try:
        return LEGACY_STATE.validate_python(value, strict=True, extra="allow")
    except ValidationError:
        raise ValueError("Invalid Model Fit handoff state") from None
