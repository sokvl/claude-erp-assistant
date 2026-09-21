import logging
import random
import time
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from typing import Any
from uuid import uuid4

import anthropic
import httpx2
from anthropic.types import Message, ToolUseBlock
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.assistant.dispatch import ToolInputError, run_tool
from app.assistant.profiles import Profile

MAX_MODEL_CALLS = 6
MID_STREAM_RETRIES = 2
TIMEOUT = anthropic.Timeout(60.0, connect=5.0, read=30.0)

RETRYABLE_ERROR_TYPES = frozenset({"overloaded_error", "api_error", "rate_limit_error"})

ERROR_MESSAGES = {
    "assistant_busy": "The assistant is busy right now. Please try again in a moment.",
    "assistant_unavailable": "The assistant is not available right now. Please contact IT.",
    "interrupted": "The answer was interrupted. Please ask again.",
    "refused": "The assistant can't help with that request.",
    "empty_answer": "No answer was produced. Please rephrase the question.",
    "database_unavailable": "The database is unavailable. Please try again later.",
    "too_many_steps": "The lookup took too many steps. Please ask a more specific question.",
    "conflict": "This conversation changed in the meantime. Please send your message again.",
    "unexpected_error": "Something went wrong. Please try again.",
}

TOOL_FAILURE_MESSAGE = "The tool failed unexpectedly."

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str


@dataclass(frozen=True)
class ChartRef:
    chart_id: str


@dataclass(frozen=True)
class Answer:
    text: str
    truncated: bool


@dataclass(frozen=True)
class TraceStep:
    name: str
    status: str
    ms: int
    summary: str
    usage: dict[str, int] | None = None


class ChatError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = ERROR_MESSAGES[code]


ChatEvent = TextDelta | ToolCall | ChartRef | Answer


@cache
def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(timeout=TIMEOUT, max_retries=2)


def build_request(profile: Profile, tools: Sequence[dict[str, Any]], today: date) -> dict[str, Any]:
    system = [{"type": "text", "text": profile.system_prompt, "cache_control": {"type": "ephemeral"}}]
    if profile.dated:
        system.append({"type": "text", "text": f"Today's date: {today.isoformat()}."})
    return {
        "model": profile.model,
        "max_tokens": profile.max_tokens,
        "system": system,
        "tools": list(tools),
        "cache_control": {"type": "ephemeral"},
        **profile.options,
    }


def run_turn(
    client: anthropic.Anthropic,
    db: Database,
    profile: Profile,
    tools: Sequence[dict[str, Any]],
    history: Sequence[dict[str, Any]],
    user_text: str,
    steps: list[TraceStep] | None = None,
    conversation_id: str | None = None,
) -> Iterator[ChatEvent]:
    steps = [] if steps is None else steps
    run_id = uuid4().hex[:8]
    outcome = "closed"
    try:
        request = build_request(profile, tools, date.today())
        yield from _run_turn(client, db, request, history, user_text, steps, conversation_id)
        outcome = "done"
    except ChatError as exc:
        outcome = exc.code
        raise
    except Exception as exc:
        outcome = type(exc).__name__
        raise
    finally:
        _log_trace(run_id, user_text, steps, outcome)


def _run_turn(
    client: anthropic.Anthropic,
    db: Database,
    request: dict[str, Any],
    history: Sequence[dict[str, Any]],
    user_text: str,
    steps: list[TraceStep],
    conversation_id: str | None,
) -> Iterator[ChatEvent]:
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": user_text}]
    texts: list[str] = []

    for _ in range(MAX_MODEL_CALLS):
        message = yield from _stream_once(client, request, messages, bool(texts), steps)
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
                result, artifact = _tool_result(db, block, steps, conversation_id)
                if artifact:
                    yield ChartRef(artifact)
                results.append(result)
            messages = [
                *messages,
                {"role": "assistant", "content": [block.model_dump(exclude_none=True) for block in message.content]},
                {"role": "user", "content": results},
            ]
            continue

        if message.stop_reason in (None, "max_tokens"):
            raise ChatError("interrupted")
        if message.stop_reason == "refusal":
            details = message.stop_details
            logger.warning(
                "model refused: category=%s explanation=%s",
                details.category if details else None,
                details.explanation if details else None,
            )
            raise ChatError("refused")
        logger.error("unexpected stop_reason %r with %d tool_use blocks", message.stop_reason, len(tool_uses))
        raise ChatError("assistant_unavailable")

    raise ChatError("too_many_steps")


def _stream_once(
    client: anthropic.Anthropic,
    request: dict[str, Any],
    messages: Sequence[dict[str, Any]],
    separate: bool,
    steps: list[TraceStep],
) -> Generator[TextDelta, None, Message]:
    for attempt in range(MID_STREAM_RETRIES + 1):
        shown = False
        started_at = time.perf_counter()
        try:
            with client.messages.stream(**request, messages=list(messages)) as stream:
                for event in stream:
                    if event.type == "text" and event.text:
                        if separate and not shown:
                            yield TextDelta("\n\n")
                        shown = True
                        yield TextDelta(event.text)
                message = stream.get_final_message()
            break
        except (
            anthropic.RateLimitError,
            anthropic.OverloadedError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
        ) as exc:
            _record(steps, "model.call", "FAIL", started_at, type(exc).__name__)
            logger.warning("model request failed after SDK retries: %s", exc)
            raise ChatError("assistant_busy") from exc
        except anthropic.APIStatusError as exc:
            if exc.type not in RETRYABLE_ERROR_TYPES:
                _record(steps, "model.call", "FAIL", started_at, f"{type(exc).__name__} {exc.type}")
                logger.exception("model request rejected")
                raise ChatError("assistant_unavailable") from exc
            if shown or attempt == MID_STREAM_RETRIES:
                _record(steps, "model.call", "FAIL", started_at, f"{exc.type} on attempt {attempt + 1}")
                logger.warning("model stream failed with %s on attempt %d", exc.type, attempt + 1)
                raise ChatError("assistant_busy") from exc
            _record(steps, "model.call", "retry", started_at, f"{exc.type} before any text")
            logger.warning("model stream failed with %s before any text, retrying", exc.type)
        except httpx2.TransportError as exc:
            if shown or attempt == MID_STREAM_RETRIES:
                _record(steps, "model.call", "FAIL", started_at, f"{type(exc).__name__} on attempt {attempt + 1}")
                logger.warning("model stream dropped on attempt %d: %r", attempt + 1, exc)
                raise ChatError("interrupted") from exc
            _record(steps, "model.call", "retry", started_at, f"{type(exc).__name__} before any text")
            logger.warning("model stream dropped before any text, retrying: %r", exc)
        time.sleep(min(0.5 * 2**attempt, 8.0) * (1 - 0.25 * random.random()))

    usage = message.usage
    tool_uses = sum(1 for block in message.content if block.type == "tool_use")
    text_chars = sum(len(block.text) for block in message.content if block.type == "text")
    _record(
        steps,
        "model.call",
        "ok",
        started_at,
        f"stop={message.stop_reason} tool_use={tool_uses} text={text_chars}",
        usage={
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": usage.cache_read_input_tokens or 0,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens or 0,
        },
    )
    return message


def _tool_result(
    db: Database,
    block: ToolUseBlock,
    steps: list[TraceStep],
    conversation_id: str | None,
) -> tuple[dict[str, Any], str | None]:
    name = f"tool {block.name}"
    started_at = time.perf_counter()
    try:
        output = run_tool(db, block.name, block.input, conversation_id)
    except ToolInputError as exc:
        _record(steps, name, "is_error", started_at, str(exc)[:80])
        return {"type": "tool_result", "tool_use_id": block.id, "content": str(exc), "is_error": True}, None
    except PyMongoError as exc:
        _record(steps, name, "FAIL", started_at, type(exc).__name__)
        logger.exception("tool %s failed on the database", block.name)
        raise ChatError("database_unavailable") from exc
    except Exception as exc:
        _record(steps, name, "is_error", started_at, f"unexpected {type(exc).__name__}")
        logger.exception("tool %s failed unexpectedly", block.name)
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": TOOL_FAILURE_MESSAGE,
            "is_error": True,
        }, None
    _record(steps, name, "ok", started_at, f"{len(output.content)} chars")
    return {"type": "tool_result", "tool_use_id": block.id, "content": output.content}, output.artifact


def _record(
    steps: list[TraceStep],
    name: str,
    status: str,
    started_at: float,
    summary: str,
    usage: dict[str, int] | None = None,
) -> None:
    ms = round((time.perf_counter() - started_at) * 1000)
    steps.append(TraceStep(name, status, ms, summary, usage))


def format_trace(run_id: str, question: str, steps: Sequence[TraceStep], outcome: str) -> str:
    lines = [f'[trace run_id={run_id}]  "{question[:80]}"']
    lines += [
        f"  step {number:<2} {step.name:<28} {step.status:<8} {step.ms:>6}ms  -> {step.summary}"
        for number, step in enumerate(steps, start=1)
    ]
    lines.append(f"  outcome: {outcome}")
    return "\n".join(lines)


def _log_trace(run_id: str, question: str, steps: list[TraceStep], outcome: str) -> None:
    logger.info(
        format_trace(run_id, question, steps, outcome),
        extra={"run_id": run_id, "trace": list(steps), "outcome": outcome},
    )
