import os
from collections.abc import Iterator
from typing import Any

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from pymongo.database import Database

from app.assistant.chat import Answer, ChatError, TextDelta, ToolCall, get_client, run_turn
from app.assistant.memory import ConversationStore, get_store
from app.assistant.tools import build_tools
from app.db import get_database
from app.limits import MAX_CHAT_MESSAGE_LENGTH
from app.security import require_api_key

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(require_api_key)])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = Field(None, max_length=64)
    message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_LENGTH)


def assistant_client() -> anthropic.Anthropic:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistant is not configured: set ANTHROPIC_API_KEY",
        )
    return get_client()


def chat_tools(db: Database = Depends(get_database)) -> list[dict[str, Any]]:
    return build_tools(db)


def resolve_conversation(
    body: ChatRequest,
    store: ConversationStore = Depends(get_store),
) -> tuple[str, list[dict[str, Any]]]:
    conversation_id = body.conversation_id or store.create()
    history = store.history(conversation_id)
    if history is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown conversation")
    return conversation_id, history


@router.post("", response_class=EventSourceResponse)
def chat(
    body: ChatRequest,
    client: anthropic.Anthropic = Depends(assistant_client),
    conversation: tuple[str, list[dict[str, Any]]] = Depends(resolve_conversation),
    tools: list[dict[str, Any]] = Depends(chat_tools),
    db: Database = Depends(get_database),
    store: ConversationStore = Depends(get_store),
) -> Iterator[ServerSentEvent]:
    conversation_id, history = conversation
    yield ServerSentEvent(event="conversation", data={"conversation_id": conversation_id})
    try:
        for event in run_turn(client, db, tools, history, body.message):
            if isinstance(event, TextDelta):
                yield ServerSentEvent(event="text", data={"text": event.text})
            elif isinstance(event, ToolCall):
                yield ServerSentEvent(event="tool", data={"name": event.name})
            elif isinstance(event, Answer):
                if not store.append_turn(conversation_id, len(history), body.message, event.text):
                    raise ChatError("conflict")
                yield ServerSentEvent(event="done", data={"truncated": event.truncated})
    except ChatError as exc:
        yield ServerSentEvent(event="error", data={"code": exc.code, "message": exc.message})
