from contextlib import AbstractContextManager
from typing import Protocol

from model_fit.autoswitch.interfaces.conversation import NativeConversation


class NativeConversationFactory(Protocol):
    def __call__(
        self, cwd: object, /
    ) -> AbstractContextManager[NativeConversation]: ...
