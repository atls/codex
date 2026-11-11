from typing_extensions import TypedDict
from pydantic import ConfigDict, with_config


@with_config(ConfigDict(extra="ignore"))
class ActiveProfile(TypedDict):
    model: str
    effort: str
    speed: str | None
