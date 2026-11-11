from typing import Literal, TypeAlias

from pydantic import ConfigDict, with_config
from typing_extensions import TypedDict


AnswerVerdict: TypeAlias = Literal["relevant", "unrelated", "uncertain"]


@with_config(ConfigDict(extra="forbid"))
class RelevanceDecision(TypedDict):
    verdict: AnswerVerdict
