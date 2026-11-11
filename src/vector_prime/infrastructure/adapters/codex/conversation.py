from vector_prime.application.handoff.types.source import HandoffSource
from collections.abc import Callable
from types import TracebackType
from typing import Self

from vector_prime.application.handoff.types.replay import BoundReplay, UnboundReplay
from vector_prime.infrastructure.adapters.codex.transport.reader import AppServerReader
from vector_prime.application.submission.types.json import JsonValue
from vector_prime.application.submission.decoding import (
    checked_content,
    checked_object,
    native_content,
)
from vector_prime.application.submission.helpers.content import input_text
from vector_prime.application.handoff.control_message import CONTROL_PROMPTS
from vector_prime.application.assessment.decoding import required_text, optional_text

import vector_prime.infrastructure.adapters.codex.chat_profile as native_settings
import vector_prime.infrastructure.adapters.codex.history as conversation
from vector_prime.application.handoff.types.accepted_input import (
    AcceptedNativeInput,
)
from vector_prime.application.handoff.types.queue_receipt import NativeQueueReceipt
from vector_prime.application.handoff.errors.queue_rejection import NativeQueueRejection
from vector_prime.infrastructure.adapters.codex.transport.exceptions.rpc import (
    AppServerRPCError,
)


class ConversationGateway:
    def __init__(
        self,
        reader: AppServerReader,
        queue_reader: Callable[
            [AppServerReader, str], set[str]
        ] = conversation.queued_ids,
    ) -> None:
        self.reader = reader
        self.manager = reader
        self.queue_reader = queue_reader

    def __enter__(self) -> Self:
        self.reader = self.manager.__enter__()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.manager.__exit__(exception_type, error, traceback)

    def parent_thread_id(self, thread_id: str) -> str | None:
        thread = checked_object(
            self.reader.call(
                "thread/read",
                {"threadId": thread_id, "includeTurns": False},
                conversation.RPC_TIMEOUT_SECONDS,
            )["thread"]
        )
        return optional_text(thread["parentThreadId"])

    def latest_turn_id(self, thread_id: str) -> str | None:
        page = self.reader.call(
            "thread/turns/list",
            {
                "threadId": thread_id,
                "limit": 1,
                "itemsView": "notLoaded",
                "sortDirection": "desc",
            },
            conversation.RPC_TIMEOUT_SECONDS,
        )
        turns = checked_content(page["data"])
        return required_text(turns[0]["id"]) if turns else None

    def queued_ids(self, thread_id: str) -> set[str]:
        return self.queue_reader(self.reader, thread_id)

    def source_input(
        self, thread_id: str, turn_id: str, *, include_steering: bool = False
    ) -> list[dict[str, JsonValue]]:
        return checked_content(
            conversation.source_input(
                self.reader, thread_id, turn_id, include_steering=include_steering
            )
        )

    def accepted_input(self, thread_id: str, turn_id: str) -> AcceptedNativeInput:
        messages = conversation.source_messages(self.reader, thread_id, turn_id)
        content = [
            value
            for index, message in enumerate(messages)
            if index == 0
            or input_text(checked_content(message["content"])).strip()
            not in CONTROL_PROMPTS
            for value in checked_content(message["content"])
        ]
        return AcceptedNativeInput(
            message_id=required_text(messages[0]["id"]),
            client_message_id=optional_text(messages[0].get("clientId")),
            content=checked_content(content),
            source_content=checked_content(messages[0]["content"]),
        )

    def handoff_input(
        self, thread_id: str, source: HandoffSource
    ) -> list[dict[str, JsonValue]]:
        return checked_content(
            conversation.handoff_input(self.reader, thread_id, source)
        )

    def replay_finished(
        self, thread_id: str, replay: BoundReplay | UnboundReplay
    ) -> bool:
        return conversation.replay_finished(self.reader, thread_id, replay)

    def source_terminal_without_replay(
        self, thread_id: str, source_turn_id: str, current_turn_id: str
    ) -> bool:
        return conversation.source_terminal_without_replay(
            self.reader, thread_id, source_turn_id, current_turn_id
        )

    def unsubmitted_successor(
        self, thread_id: str, source_turn_id: str, current_turn_id: str
    ) -> bool:
        return conversation.unsubmitted_successor(
            self.reader, thread_id, source_turn_id, current_turn_id
        )

    def profile(self, thread_id: str) -> tuple[str | None, str | None]:
        return native_settings.profile(self.reader, thread_id)

    def enqueue(
        self, thread_id: str, turn_id: str, content: list[dict[str, JsonValue]]
    ) -> NativeQueueReceipt | NativeQueueRejection:
        try:
            result = self.reader.call(
                "thread/queue/add",
                {
                    "threadId": thread_id,
                    "clientUserMessageId": turn_id,
                    "input": list[JsonValue](content),
                },
                conversation.RPC_TIMEOUT_SECONDS,
            )
        except AppServerRPCError as error:
            return NativeQueueRejection(error)
        receipt = checked_object(result["queuedSubmission"])
        accepted_content = receipt.get("input")
        return NativeQueueReceipt(
            required_text(receipt["id"]),
            accepted_content if native_content(accepted_content) else None,
        )

    def delete(self, thread_id: str, submission_id: str) -> bool:
        deleted = self.reader.call(
            "thread/queue/delete",
            {"threadId": thread_id, "queuedSubmissionId": submission_id},
            conversation.RPC_TIMEOUT_SECONDS,
        ).get("deleted")
        if not isinstance(deleted, bool):
            raise ValueError("Native queue deletion outcome is unavailable")
        return deleted

    def replay_input(
        self, thread_id: str, turn_id: str
    ) -> list[dict[str, JsonValue]] | None:
        replay = self.reader.call(
            "thread/items/list",
            {
                "threadId": thread_id,
                "turnId": turn_id,
                "limit": conversation.QUEUE_PAGE_LIMIT,
            },
            conversation.RPC_TIMEOUT_SECONDS,
        )
        messages = [
            item
            for row in checked_content(replay["data"])
            if (item := checked_object(row["item"])).get("type") == "userMessage"
        ]
        if replay.get("nextCursor") or len(messages) != 1:
            return None
        content = messages[0].get("content", [])
        return content if native_content(content) else None
