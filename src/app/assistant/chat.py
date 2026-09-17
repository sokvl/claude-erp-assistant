import logging
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

import anthropic
import httpx2
from anthropic.types import Message, ToolUseBlock
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.assistant.dispatch import ToolInputError, run_tool
from app.assistant.prompts import SYSTEM_PROMPT

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 4096
MAX_MODEL_CALLS = 6
TIMEOUT = anthropic.Timeout(60.0, connect=5.0, read=30.0)

RETRYABLE_ERROR_TYPES = frozenset({"overloaded_error", "api_error", "rate_limit_error"})

ERROR_MESSAGES = {
    "assistant_busy": "The assistant is busy right now. Please try again in a moment.",
    "assistant_unavailable": "The assistant is not available right now. Please contact IT.",
    "interrupted": "The answer was interrupted. Please ask again.",
    "refused": "The assistant can't help with that request.",
    "empty_answer": "No answer was produced. Please rephrase the question.",
    "database_unavailable": "The product database is unavailable. Please try again later.",
    "too_many_steps": "The lookup took too many steps. Please ask a more specific question.",
    "conflict": "This conversation changed in the meantime. Please send your message again.",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str


@dataclass(frozen=True)
class Answer:
    text: str
    truncated: bool


class ChatError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = ERROR_MESSAGES[code]


ChatEvent = TextDelta | ToolCall | Answer


@cache
def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(timeout=TIMEOUT, max_retries=2)


def run_turn(
    client: anthropic.Anthropic,
    db: Database,
    tools: Sequence[dict[str, Any]],
    history: Sequence[dict[str, Any]],
    user_text: str,
) -> Iterator[ChatEvent]:
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": user_text}]
    texts: list[str] = []

    for _ in range(MAX_MODEL_CALLS):
        message = yield from _stream_once(client, tools, messages, separate=bool(texts))
        texts.extend(block.text for block in message.content if block.type == "text" and block.text.strip())
        tool_uses = [block for block in message.content if block.type == "tool_use"]

        if message.stop_reason in ("end_turn", "max_tokens") and not tool_uses:
            if not texts:
                raise ChatError("empty_answer")
            yield Answer("\n\n".join(texts), truncated=message.stop_reason == "max_tokens")
            return

        if message.stop_reason == "tool_use" and tool_uses:
            results = []
            for block in tool_uses:
                yield ToolCall(block.name)
                results.append(_tool_result(db, block))
            messages = [
                *messages,
                {"role": "assistant", "content": [block.model_dump(exclude_none=True) for block in message.content]},
                {"role": "user", "content": results},
            ]
            continue

        if message.stop_reason in (None, "max_tokens"):
            raise ChatError("interrupted")
        if message.stop_reason == "refusal":
            raise ChatError("refused")
        logger.error("unexpected stop_reason %r with %d tool_use blocks", message.stop_reason, len(tool_uses))
        raise ChatError("assistant_unavailable")

    raise ChatError("too_many_steps")


def _stream_once(
    client: anthropic.Anthropic,
    tools: Sequence[dict[str, Any]],
    messages: Sequence[dict[str, Any]],
    separate: bool,
) -> Generator[TextDelta, None, Message]:
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=list(tools),
            messages=list(messages),
            cache_control={"type": "ephemeral"},
        ) as stream:
            started = False
            for event in stream:
                if event.type == "text" and event.text:
                    if separate and not started:
                        yield TextDelta("\n\n")
                    started = True
                    yield TextDelta(event.text)
            message = stream.get_final_message()
    except (
        anthropic.RateLimitError,
        anthropic.OverloadedError,
        anthropic.InternalServerError,
        anthropic.APIConnectionError,
    ) as exc:
        logger.warning("model request failed and is retryable: %s", exc)
        raise ChatError("assistant_busy") from exc
    except anthropic.APIStatusError as exc:
        if exc.type in RETRYABLE_ERROR_TYPES:
            logger.warning("model stream failed with %s", exc.type)
            raise ChatError("assistant_busy") from exc
        logger.exception("model request rejected")
        raise ChatError("assistant_unavailable") from exc
    except httpx2.TransportError as exc:
        logger.warning("model stream dropped: %r", exc)
        raise ChatError("interrupted") from exc

    usage = message.usage
    logger.info(
        "model usage input=%s output=%s cache_read=%s cache_write=%s stop=%s",
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_input_tokens,
        usage.cache_creation_input_tokens,
        message.stop_reason,
    )
    return message


def _tool_result(db: Database, block: ToolUseBlock) -> dict[str, Any]:
    try:
        content = run_tool(db, block.name, block.input)
    except ToolInputError as exc:
        return {"type": "tool_result", "tool_use_id": block.id, "content": str(exc), "is_error": True}
    except PyMongoError as exc:
        logger.exception("tool %s failed on the database", block.name)
        raise ChatError("database_unavailable") from exc
    return {"type": "tool_result", "tool_use_id": block.id, "content": content}
