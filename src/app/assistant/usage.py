import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.assistant.chat import TraceStep
from app.assistant.profiles import ADVISOR_MODEL, ANALYST_MODEL, Profile

USAGE_COLLECTION = "chat_usage"
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
PRICE_PER_MILLION_TOKENS = {
    ADVISOR_MODEL: {
        "input_tokens": 1.00,
        "output_tokens": 5.00,
        "cache_creation_input_tokens": 1.25,
        "cache_read_input_tokens": 0.10,
    },
    ANALYST_MODEL: {
        "input_tokens": 2.00,
        "output_tokens": 10.00,
        "cache_creation_input_tokens": 2.50,
        "cache_read_input_tokens": 0.20,
    },
}

logger = logging.getLogger(__name__)


def total_tokens(steps: Sequence[TraceStep]) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for step in steps:
        totals.update(step.usage or {})
    return {field: totals[field] for field in TOKEN_FIELDS}


def cost_usd(tokens: Mapping[str, int], model: str) -> float:
    prices = PRICE_PER_MILLION_TOKENS[model]
    return sum(tokens[field] * prices[field] for field in TOKEN_FIELDS) / 1_000_000


def record_usage(
    db: Database,
    conversation_id: str,
    profile: Profile,
    steps: Sequence[TraceStep],
    outcome: str,
) -> None:
    tokens = total_tokens(steps)
    document = {
        "conversationId": conversation_id,
        "createdAt": datetime.now(UTC),
        "assistant": profile.name,
        "model": profile.model,
        "outcome": outcome,
        "modelCalls": sum(step.usage is not None for step in steps),
        "tokens": tokens,
        "costUsd": cost_usd(tokens, profile.model),
    }
    try:
        db[USAGE_COLLECTION].insert_one(document)
    except PyMongoError:
        logger.exception("could not record token usage for conversation %s", conversation_id)
