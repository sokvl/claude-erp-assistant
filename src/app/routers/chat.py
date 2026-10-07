import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field
from pymongo.database import Database

from app.assistant.chat import (
    Answer,
    ChartRef,
    ChatError,
    PendingActionRef,
    TextDelta,
    ToolCall,
    TraceStep,
    get_client,
    run_turn,
)
from app.assistant.conversations import CONVERSATION_COLLECTION, ConversationStore, History
from app.assistant.profiles import PROFILES, AssistantName
from app.assistant.tools import TOOLS
from app.assistant.usage import record_usage
from app.auth.roles import Principal, Role, allows
from app.db import get_database
from app.limits import MAX_CHAT_MESSAGE_LENGTH, MAX_CONVERSATION_ID_LENGTH
from app.security import require_role
from app.vault import secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = Field(None, max_length=MAX_CONVERSATION_ID_LENGTH)
    message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_LENGTH)
    assistant: AssistantName = AssistantName.ADVISOR


def assistant_client() -> anthropic.Anthropic:
    if not (secret("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistant is not configured: set ANTHROPIC_API_KEY",
        )
    return get_client()


def chat_principal(
    body: ChatRequest,
    principal: Principal = Depends(require_role(Role.CONSULTANT)),
) -> Principal:
    required = PROFILES[body.assistant].role
    if not allows(principal.role, required):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"The {body.assistant} assistant requires the {required} role",
        )
    return principal


def chat_store(body: ChatRequest, db: Database = Depends(get_database)) -> ConversationStore:
    return ConversationStore(db[CONVERSATION_COLLECTION], body.assistant)


def chat_tools(body: ChatRequest) -> list[dict[str, Any]]:
    return TOOLS[body.assistant]


def resolve_conversation(
    body: ChatRequest,
    principal: Principal = Depends(chat_principal),
    store: ConversationStore = Depends(chat_store),
) -> tuple[str, History]:
    conversation_id = body.conversation_id or store.create(principal.username, body.message, datetime.now(UTC))
    history = store.history(conversation_id, principal.username)
    if history is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown conversation")
    return conversation_id, history


@router.post("", response_class=EventSourceResponse)
def chat(
    body: ChatRequest,
    principal: Principal = Depends(chat_principal),
    client: anthropic.Anthropic = Depends(assistant_client),
    conversation: tuple[str, History] = Depends(resolve_conversation),
    tools: list[dict[str, Any]] = Depends(chat_tools),
    db: Database = Depends(get_database),
    store: ConversationStore = Depends(chat_store),
) -> Iterator[ServerSentEvent]:
    profile = PROFILES[body.assistant]
    conversation_id, history = conversation
    yield ServerSentEvent(event="conversation", data={"conversation_id": conversation_id})
    steps: list[TraceStep] = []
    chart_ids: list[str] = []
    outcome = "closed"
    try:
        for event in run_turn(
            client, db, profile, tools, history.messages, body.message, steps, conversation_id, principal.username
        ):
            if isinstance(event, TextDelta):
                yield ServerSentEvent(event="text", data={"text": event.text})
            elif isinstance(event, ToolCall):
                yield ServerSentEvent(event="tool", data={"name": event.name})
            elif isinstance(event, ChartRef):
                chart_ids.append(event.chart_id)
                yield ServerSentEvent(event="chart", data={"chart_id": event.chart_id})
            elif isinstance(event, PendingActionRef):
                yield ServerSentEvent(
                    event="confirmation_required",
                    data={
                        "pending_action_id": event.pending_action_id,
                        "invoice_id": event.invoice_id,
                        "consequence": event.consequence,
                    },
                )
            elif isinstance(event, Answer):
                saved = store.append_turn(
                    conversation_id, history.turns, body.message, event.text, chart_ids, datetime.now(UTC)
                )
                if not saved:
                    raise ChatError("conflict")
                outcome = "done"
                yield ServerSentEvent(event="done", data={"truncated": event.truncated})
    except ChatError as exc:
        outcome = exc.code
        yield ServerSentEvent(event="error", data={"code": exc.code, "message": exc.message})
    except Exception:
        logger.exception("chat turn failed unexpectedly")
        error = ChatError("unexpected_error")
        outcome = error.code
        yield ServerSentEvent(event="error", data={"code": error.code, "message": error.message})
    finally:
        record_usage(db, conversation_id, profile, steps, outcome)
