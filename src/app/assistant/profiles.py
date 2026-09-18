from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import anthropic

from app.assistant.prompts import ANALYST_PROMPT, SYSTEM_PROMPT

ADVISOR_MODEL = "claude-haiku-4-5-20251001"
ANALYST_MODEL = "claude-sonnet-5"


class AssistantName(StrEnum):
    ADVISOR = "advisor"
    ANALYST = "analyst"


@dataclass(frozen=True)
class Profile:
    name: AssistantName
    model: str
    system_prompt: str
    max_tokens: int
    options: Mapping[str, Any] = field(default_factory=dict)
    dated: bool = False


ADVISOR = Profile(
    name=AssistantName.ADVISOR,
    model=ADVISOR_MODEL,
    system_prompt=SYSTEM_PROMPT,
    max_tokens=4096,
)

ANALYST = Profile(
    name=AssistantName.ANALYST,
    model=ANALYST_MODEL,
    system_prompt=ANALYST_PROMPT,
    max_tokens=64_000,
    options={
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
        "timeout": anthropic.Timeout(120.0, connect=5.0, read=90.0),
    },
    dated=True,
)

PROFILES: Mapping[AssistantName, Profile] = {profile.name: profile for profile in (ADVISOR, ANALYST)}
