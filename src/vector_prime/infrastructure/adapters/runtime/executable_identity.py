import shlex
import sys
from pathlib import Path


def verified_python_arguments(value: object) -> list[str] | None:
    if not isinstance(value, str):
        return None
    try:
        command = shlex.split(value)
        if not command:
            return None
        candidate, active = Path(command[0]), Path(sys.executable)
        if (
            not candidate.is_absolute()
            or candidate.parent.resolve() != active.parent.resolve()
            or not candidate.samefile(active)
        ):
            return None
    except (OSError, ValueError):
        return None
    return command[1:]
