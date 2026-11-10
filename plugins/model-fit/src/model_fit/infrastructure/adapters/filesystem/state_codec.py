from pydantic import TypeAdapter, ValidationError

from model_fit.application.switch.types.state import ProcessSnapshot


LEGACY_STATE = TypeAdapter(ProcessSnapshot)


def decode_state(value: object) -> ProcessSnapshot:
    try:
        return LEGACY_STATE.validate_python(value, strict=True, extra="allow")
    except ValidationError:
        raise ValueError("Invalid Model Fit handoff state") from None
