from typing import TypedDict


class ActiveProfile(TypedDict):
    model: str
    effort: str
    speed: str | None
