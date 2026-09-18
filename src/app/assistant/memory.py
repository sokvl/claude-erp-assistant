from collections import OrderedDict
from threading import Lock
from typing import Any
from uuid import uuid4

from app.assistant.profiles import AssistantName
from app.limits import MAX_CONVERSATION_TURNS, MAX_CONVERSATIONS

MAX_MESSAGES = 2 * MAX_CONVERSATION_TURNS


class ConversationStore:
    def __init__(self) -> None:
        self._conversations: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._lock = Lock()

    def create(self) -> str:
        conversation_id = uuid4().hex
        with self._lock:
            self._conversations[conversation_id] = []
            while len(self._conversations) > MAX_CONVERSATIONS:
                self._conversations.popitem(last=False)
        return conversation_id

    def history(self, conversation_id: str) -> list[dict[str, Any]] | None:
        with self._lock:
            messages = self._conversations.get(conversation_id)
            if messages is None:
                return None
            self._conversations.move_to_end(conversation_id)
            return list(messages)

    def append_turn(self, conversation_id: str, expected_length: int, user_text: str, answer: str) -> bool:
        with self._lock:
            messages = self._conversations.get(conversation_id)
            if messages is None or len(messages) != expected_length:
                return False
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": answer})
            overflow = len(messages) - MAX_MESSAGES
            if overflow > 0:
                del messages[:overflow]
            self._conversations.move_to_end(conversation_id)
            return True


stores = {assistant: ConversationStore() for assistant in AssistantName}


def get_store(assistant: AssistantName) -> ConversationStore:
    return stores[assistant]
