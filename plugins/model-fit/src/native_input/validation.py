from typing import TypeGuard

from model_fit.native_input.types.json import JsonValue


def json_value(value: object) -> TypeGuard[JsonValue]:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and json_value(item) for key, item in value.items()
        )
    return False


def json_object(value: object) -> TypeGuard[dict[str, JsonValue]]:
    return isinstance(value, dict) and json_value(value)


def checked_object(value: object) -> dict[str, JsonValue]:
    if not json_object(value):
        raise ValueError("Native input is not a JSON object")
    return value


def native_content(value: object) -> TypeGuard[list[dict[str, JsonValue]]]:
    return isinstance(value, list) and all(
        isinstance(item, dict) and json_value(item) for item in value
    )


def checked_content(value: object) -> list[dict[str, JsonValue]]:
    if not native_content(value):
        raise ValueError("Native message content is not an array of JSON objects")
    return value
