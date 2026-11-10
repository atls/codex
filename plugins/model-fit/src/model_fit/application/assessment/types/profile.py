from typing_extensions import TypedDict


class ActiveProfile(TypedDict):
    model: str
    effort: str
    speed: str | None
