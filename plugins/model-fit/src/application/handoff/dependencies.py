from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Callable

from model_fit.application.handoff.ports.actions import Actions
from model_fit.application.handoff.ports.conversation import Conversation
from model_fit.application.handoff.ports.inputs import Inputs
from model_fit.application.handoff.ports.presentation import Presentation
from model_fit.application.handoff.ports.recommendations import Recommendations
from model_fit.application.handoff.ports.store import Store
from model_fit.application.handoff.requests.prompt import Prompt


@dataclass(frozen=True)
class Dependencies:
    state: Store
    cache: Recommendations
    native: Callable[[object], AbstractContextManager[Conversation]]
    read_context: Callable[[Prompt], dict[str, Any]]
    assess: Callable[[dict[str, Any]], dict[str, Any]]
    audit: Callable[..., Any]
    input: Inputs
    presentation: Presentation
    actions: Actions
    assessment_failure: tuple[type[Exception], ...]
    context_failure: type[Exception]
    context_reason: Callable[[Exception, str], str | None]
    queue_rejection: type[Exception]
    relevance: Callable[[str, str, str], str]
    clock: Callable[[], float]
    caller_thread: str | None
    working_directory: Callable[[], str]
