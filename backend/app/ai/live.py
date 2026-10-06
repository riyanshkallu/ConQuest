"""Live AI: real LLM calls for the Player Analyzer and AI Character.

Every reply is validated with Pydantic plus the plan's character rules. Anything that
fails falls back to the mock logic (pre-written lines), so a round never gets stuck.
"""

from __future__ import annotations

import random
import re
from typing import Literal

from pydantic import BaseModel, Field, RootModel, field_validator, model_validator

from .. import engine
from ..config import Settings
from ..engine import Analysis
from ..flags import GREEN_FLAGS, RED_FLAGS
from ..scenarios import Scenario, ai_var_specs
from . import generator, prompts
from .base import CharacterMove, TurnContext
from .llm import LLM, parse_models
from .mock import mock_analysis, mock_character_move

MAX_WORDS = 70
_REAL_DOMAIN_RE = re.compile(r"\b[\w-]+\.(com|net|org|io|co|gov|us|edu|app|me|ly)\b", re.IGNORECASE)
_BLOCKLIST_RE = re.compile(r"\b(social security|ssn|kill|hurt you|sexy|as an ai|language model)\b", re.IGNORECASE)
_ASKS_FOR_SECRET_RE = re.compile(r"\b(send|give|tell|read|share|text)\b[^.?!]{0,40}\b(code|password|pin)\b", re.IGNORECASE)


class AnalyzerOut(BaseModel):
    decision_type: Literal[prompts.DECISION_TYPES]  # type: ignore[valid-type]
    suspicion_change: int = 0
    trust_change: int = 0
    tactic_recognized: str | None = None
    flag_noticed: str | None = None
    mistake: bool = False
    reason: str = Field(default="", max_length=240)

    @field_validator("suspicion_change", "trust_change")
    @classmethod
    def clamp(cls, v: int) -> int:
        return max(-20, min(20, v))


class CharacterOut(BaseModel):
    message: str = Field(min_length=1, max_length=600)
    tactic: str | None = None
    green_flag: str | None = None
    pressure: int = Field(default=0, ge=0, le=100)


def check_character(out: CharacterOut, ctx: TurnContext) -> str | None:
    """The plan's character rules. Returns a problem description, or None if OK."""
    text = out.message
    if len(text.split()) > MAX_WORDS:
        return "too long"
    if ctx.state.is_scam:
        if out.tactic not in ctx.version["allowed_tactics"]:
            return f"tactic {out.tactic!r} not allowed"
    else:
        if out.green_flag not in ctx.version["allowed_flags"]:
            return f"green flag {out.green_flag!r} not allowed"
        for match in _ASKS_FOR_SECRET_RE.finditer(text):
            around = text[max(0, match.start() - 20):match.end()]  # "don't send us codes" is fine
            if not re.search(r"\b(never|don't|do not|not)\b", around, re.IGNORECASE):
                return "legit contact asked for a secret"
    if _REAL_DOMAIN_RE.search(text):
        return "real-looking website"
    if engine.blocked_reason(text, ctx.state.id_card):
        return "real-looking number"
    if _BLOCKLIST_RE.search(text):
        return "blocked word"
    if ctx.state.id_card.verification_code in re.sub(r"\D", "", text):
        return "mentioned the code itself"
    return None


class GeneratedVars(RootModel[dict[str, str]]):
    """The Scenario Generator's reply: {"bank": "Maple Valley Credit Union", ...}."""

    @model_validator(mode="before")
    @classmethod
    def unwrap(cls, data):
        # Some models wrap the answer: {"invent_these": {"bank": ...}}. Use the inner object.
        if isinstance(data, dict):
            nested = [v for v in data.values() if isinstance(v, dict)]
            if len(nested) == 1:
                return nested[0]
        return data


class LiveAI:
    def __init__(self, settings: Settings):
        self.llm = LLM(settings)
        self.analyzer_models = parse_models(settings.analyzer_models)
        self.character_models = parse_models(settings.character_models)
        self.generator_models = parse_models(settings.generator_models)
        self.generator_timeout = settings.generator_timeout_seconds
        self.rng = random.Random()

    async def scenario_vars(self, scenario: Scenario) -> dict[str, str] | None:
        if not ai_var_specs(scenario):
            return None
        out = await self.llm.json_call(
            self.generator_models, generator.generator_system(), generator.generator_user(scenario, self.rng),
            GeneratedVars, check=lambda o: generator.check_vars(o.root, scenario),
            max_tokens=300, timeout=self.generator_timeout,
        )
        return {k: v.strip() for k, v in out.root.items()} if out else None

    async def analyze(self, ctx: TurnContext) -> Analysis:
        out = await self.llm.json_call(
            self.analyzer_models, prompts.analyzer_system(ctx), prompts.analyzer_user(ctx),
            AnalyzerOut, max_tokens=300,
        )
        if out is None:
            return mock_analysis(ctx)
        return Analysis(
            decision_type=out.decision_type,
            suspicion_change=out.suspicion_change,
            trust_change=out.trust_change,
            tactic_recognized=out.tactic_recognized if out.tactic_recognized in RED_FLAGS else None,
            flag_noticed=out.flag_noticed if out.flag_noticed in GREEN_FLAGS else None,
            mistake=out.mistake,
            reason=out.reason.strip(),
        )

    async def character_move(self, ctx: TurnContext) -> CharacterMove:
        out = await self.llm.json_call(
            self.character_models, prompts.character_system(ctx), prompts.character_user(ctx),
            CharacterOut, check=lambda o: check_character(o, ctx), max_tokens=400,
        )
        if out is None:
            return mock_character_move(ctx)
        flag = out.tactic if ctx.state.is_scam else out.green_flag
        return CharacterMove(message=out.message.strip(), flag=flag, pressure=out.pressure)
