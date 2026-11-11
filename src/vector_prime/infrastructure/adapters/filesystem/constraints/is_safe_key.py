import re
from typing import TypeGuard

KEY = re.compile("[A-Za-z0-9-]{1,100}")


def is_safe_key(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and KEY.fullmatch(value) is not None
