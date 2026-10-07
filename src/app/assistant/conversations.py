from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from app.assistant.profiles import AssistantName
from app.limits import (
    CONVERSATION_TTL_DAYS,
    MAX_CONVERSATION_TITLE_LENGTH,
    MAX_CONVERSATION_TURNS,
    MAX_STORED_TURNS,
    QUERY_TIMEOUT_MS,
)

CONVERSATION_COLLECTION = "conversations"
MODEL_MESSAGES = 2 * MAX_CONVERSATION_TURNS
STORED_MESSAGES = 2 * MAX_STORED_TURNS


@dataclass(frozen=True)
class History:
    turns: int
    messages: list[dict[str, Any]]


class ConversationStore:
    def __init__(self, collection: Any, assistant: AssistantName) -> None:
        self._collection = collection
        self._assistant = str(assistant)

    def create(self, owner: str, title: str, now: datetime) -> str:
        conversation_id = uuid4().hex
        self._collection.insert_one(
            {
                "_id": conversation_id,
                "username": owner,
                "assistant": self._assistant,
                "title": title.strip()[:MAX_CONVERSATION_TITLE_LENGTH],
                "createdAt": now,
                "lastMessageAt": now,
                "expiresAt": now + timedelta(days=CONVERSATION_TTL_DAYS),
                "turns": 0,
                "messages": [],
            }
        )
        return conversation_id

    def history(self, conversation_id: str, owner: str) -> History | None:
        document = self._collection.find_one(
            {"_id": conversation_id, "username": owner, "assistant": self._assistant},
            {"turns": 1, "messages": {"$slice": -MODEL_MESSAGES}},
            max_time_ms=QUERY_TIMEOUT_MS,
        )
        if document is None:
            return None
        recent = document["messages"][-MODEL_MESSAGES:]
        return History(document["turns"], [{"role": message["role"], "content": message["content"]} for message in recent])

    def append_turn(
        self,
        conversation_id: str,
        expected_turns: int,
        user_text: str,
        answer: str,
        chart_ids: list[str],
        now: datetime,
    ) -> bool:
        turn = [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": answer, "chartIds": chart_ids},
        ]
        result = self._collection.update_one(
            {"_id": conversation_id, "turns": expected_turns},
            {
                "$push": {"messages": {"$each": turn, "$slice": -STORED_MESSAGES}},
                "$inc": {"turns": 1},
                "$set": {"lastMessageAt": now, "expiresAt": now + timedelta(days=CONVERSATION_TTL_DAYS)},
            },
        )
        return result.matched_count == 1
