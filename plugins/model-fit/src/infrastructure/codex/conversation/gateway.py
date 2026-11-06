import model_fit.infrastructure.codex.conversation.queries as conversation
from model_fit.application.handoff.contracts.accepted_input import AcceptedInput
from model_fit.application.handoff.contracts.receipt import Receipt


class ConversationGateway:
    def __init__(self, reader, queue_reader=conversation.queued_ids):
        self.reader = reader
        self.manager = reader
        self.queue_reader = queue_reader

    def __enter__(self):
        self.reader = self.manager.__enter__()
        return self

    def __exit__(self, *args):
        return self.manager.__exit__(*args)

    def parent_thread_id(self, thread_id):
        return self.reader.call(
            "thread/read",
            {"threadId": thread_id, "includeTurns": False},
            conversation.RPC_TIMEOUT_SECONDS,
        )["thread"]["parentThreadId"]

    def latest_turn_id(self, thread_id):
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
        return page["data"][0]["id"] if page["data"] else None

    def queued_ids(self, thread_id):
        return self.queue_reader(self.reader, thread_id)

    def source_input(self, thread_id, turn_id, **options):
        return conversation.source_input(self.reader, thread_id, turn_id, **options)

    def accepted_input(self, thread_id, turn_id):
        messages = conversation.source_messages(self.reader, thread_id, turn_id)
        content = [
            value
            for index, message in enumerate(messages)
            if index == 0
            or conversation.input_text(message["content"]).strip()
            != conversation.CONTROL_PROMPT
            for value in message["content"]
        ]
        return AcceptedInput(
            message_id=messages[0]["id"],
            client_message_id=messages[0].get("clientId"),
            content=content,
            source_content=messages[0]["content"],
        )

    def handoff_input(self, thread_id, state):
        return conversation.handoff_input(self.reader, thread_id, state)

    def replay_finished(self, thread_id, state):
        return conversation.replay_finished(self.reader, thread_id, state)

    def source_terminal_without_replay(
        self, thread_id, source_turn_id, current_turn_id
    ):
        return conversation.source_terminal_without_replay(
            self.reader, thread_id, source_turn_id, current_turn_id
        )

    def unsubmitted_successor(self, thread_id, source_turn_id, current_turn_id):
        return conversation.unsubmitted_successor(
            self.reader, thread_id, source_turn_id, current_turn_id
        )

    def profile(self, thread_id):
        thread = self.reader.call(
            "thread/read",
            {"threadId": thread_id, "includeTurns": False},
            conversation.RPC_TIMEOUT_SECONDS,
        )["thread"]
        return thread.get("model"), thread.get("reasoningEffort")

    def enqueue(self, thread_id, turn_id, content):
        result = self.reader.call(
            "thread/queue/add",
            {"threadId": thread_id, "clientUserMessageId": turn_id, "input": content},
            conversation.RPC_TIMEOUT_SECONDS,
        )

        receipt = result["queuedSubmission"]
        return Receipt(receipt["id"], receipt["input"])

    def delete(self, thread_id, submission_id):
        return self.reader.call(
            "thread/queue/delete",
            {"threadId": thread_id, "queuedSubmissionId": submission_id},
            conversation.RPC_TIMEOUT_SECONDS,
        ).get("deleted")

    def replay_input(self, thread_id, turn_id):
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
            row["item"]
            for row in replay["data"]
            if row["item"].get("type") == "userMessage"
        ]
        return (
            None
            if replay.get("nextCursor") or len(messages) != 1
            else messages[0].get("content", [])
        )
