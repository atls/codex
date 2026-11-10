from typing import TypeGuard
from pydantic import TypeAdapter, ValidationError

from model_fit.application.submission.types.json import JsonValue


JSON_VALUE = TypeAdapter(JsonValue)
CONTENT = TypeAdapter(list[dict[str, JsonValue]])


def native_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Native text field is unavailable")
    return value


def native_optional_text(value: object) -> str | None:
    return None if value is None else native_text(value)


def json_value(value: object) -> TypeGuard[JsonValue]:
    try:
        JSON_VALUE.validate_python(value, strict=True)
        return True
    except ValidationError:
        return False


def json_object(value: object) -> TypeGuard[dict[str, JsonValue]]:
    return isinstance(value, dict) and json_value(value)


def checked_object(value: object) -> dict[str, JsonValue]:
    if not json_object(value):
        raise ValueError("Native input is not a JSON object")
    return value


def native_content(value: object) -> TypeGuard[list[dict[str, JsonValue]]]:
    try:
        CONTENT.validate_python(value, strict=True)
        return True
    except ValidationError:
        return False


def checked_content(value: object) -> list[dict[str, JsonValue]]:
    if not native_content(value):
        raise ValueError("Native message content is not an array of JSON objects")
    return value
