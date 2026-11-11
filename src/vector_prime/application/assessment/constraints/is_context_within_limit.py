from typing import Annotated, TypeGuard

from pydantic import StringConstraints, TypeAdapter, ValidationError


MAX_CONTEXT_CHARS = 20000
CONTEXT = TypeAdapter(
    Annotated[str, StringConstraints(max_length=MAX_CONTEXT_CHARS)] | None
)


def is_context_within_limit(value: object) -> TypeGuard[str | None]:
    try:
        CONTEXT.validate_python(value, strict=True)
        return True
    except ValidationError:
        return False
