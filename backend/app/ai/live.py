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
from . import explainer, generator, prompts
from .base import CharacterMove, ExplainerText, ExplainRequest, TurnContext
from .llm import LLM, parse_models
from .mock import mock_analysis, mock_character_move

MAX_WORDS = 70
_REAL_DOMAIN_RE = re.compile(r"\b[\w-]+\.(com|net|org|io|co|gov|us|edu|app|me|ly)\b", re.IGNORECASE)
_BLOCKLIST_RE = re.compile(r"\b(social security|ssn|kill|hurt you|sexy|as an ai|language model)\b", re.IGNORECASE)
_ASKS_FOR_SECRET_RE = re.compile(r"\b(send|give|tell|read|share|text)\b[^.?!]{0,40}\b(code|password|pin)\b", re.IGNORECASE)
_NEGATION_RE = re.compile(r"\b(never|don't|do not|not)\b", re.IGNORECASE)
_ASK_VERBS = r"\b(?:send|give|tell|share|text|read|confirm|provide|enter|type|verify|need|reply with|what's|what is|ask for)\b"
# Things no ID card has, so the player could never answer. Asking for them breaks the game.
_NEVER_ON_CARD = [r"pins?", r"cvv", r"cvc", r"security code on the back", r"(?:3|three)[- ]digit code",
                  r"expiration date", r"expiry date", r"(?<!email )(?<!e-mail )(?<!web )address(?:es)?(?! on file)",
                  r"date of birth", r"birth ?date", r"birthday", r"maiden name", r"routing number",
                  r"account number", r"security questions?", r"driver'?s licen[cs]e"]
_TEXTING_RE = re.compile(r"\b(?:pls|plz|thx|lol|omg|btw|gonna|wanna|gotta|idk|rn)\b", re.IGNORECASE)
_LOWERCASE_RE = re.compile(r"(?:^\W*|[.!?]\s+)[a-z]|\b(?:i|u|ur)\b")  # lowercase sentence start, "i", "u", "ur"
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_FAKE_LINK_RE = re.compile(r"\S+\.example\S*")
_MENTIONS_ID_CARD_RE = re.compile(r"\bID card\b|\b(?:your|the|my) ID\b")  # "the code from your ID" breaks the story


def _not_on_card(ctx: TurnContext) -> list[str]:
    """Patterns for items this round's ID card doesn't have."""
    card, missing = ctx.state.id_card, list(_NEVER_ON_CARD)
    if not card.password:
        missing.append(r"passwords?")
    if not card.gift_card_code:
        missing.append(r"gift cards?(?: codes?)?")
    if "code_notification" not in ctx.scenario.raw:
        missing.append(r"(?:one-time|verification|login) codes?")
    return missing


def asks_off_card(text: str, ctx: TurnContext) -> bool:
    """True if the message asks for something that isn't on the ID card ("Please confirm your PIN")."""
    pattern = re.compile(_ASK_VERBS + r"[^.?!]{0,40}?\b(?:" + "|".join(_not_on_card(ctx)) + r")\b", re.IGNORECASE)
    for match in pattern.finditer(text):
        if not _NEGATION_RE.search(text[max(0, match.start() - 20):match.start()]):  # "we never ask for your PIN" is fine
            return True
    return False


def is_informal(text: str) -> bool:
    """Lowercase sentences, texting shortcuts or emojis. Fake links like secure-login.example are ignored."""
    text = _FAKE_LINK_RE.sub("Link", text)
    return bool(_LOWERCASE_RE.search(text) or _TEXTING_RE.search(text) or _EMOJI_RE.search(text))


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
    if asks_off_card(text, ctx):
        return "asked for something not on the ID card"
    if is_informal(text):
        return "informal writing"
    if _MENTIONS_ID_CARD_RE.search(text):
        return "mentioned the ID card"
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
        self.budgets = {"analyzer": settings.analyzer_budget_seconds, "character": settings.character_budget_seconds,
                        "explainer": settings.explainer_budget_seconds, "generator": settings.generator_budget_seconds}
        self.explainer_models = parse_models(settings.explainer_models)
        self.rng = random.Random()

    async def scenario_vars(self, scenario: Scenario) -> dict[str, str] | None:
        if not ai_var_specs(scenario):
            return None
        out = await self.llm.json_call(
            self.generator_models, generator.generator_system(), generator.generator_user(scenario, self.rng),
            GeneratedVars, check=lambda o: generator.check_vars(o.root, scenario),
            max_tokens=300, timeout=self.generator_timeout, budget=self.budgets["generator"],
        )
        return {k: v.strip() for k, v in out.root.items()} if out else None

    async def explain(self, request: ExplainRequest) -> ExplainerText | None:
        out = await self.llm.json_call(
            self.explainer_models, explainer.explainer_system(), explainer.explainer_user(request),
            explainer.ExplainerOut, check=lambda o: explainer.check_explanation(o, request), max_tokens=900,
            budget=self.budgets["explainer"],
        )
        return explainer.to_text(out, request) if out else None

    async def analyze(self, ctx: TurnContext) -> Analysis:
        out = await self.llm.json_call(
            self.analyzer_models, prompts.analyzer_system(ctx), prompts.analyzer_user(ctx),
            AnalyzerOut, max_tokens=300, budget=self.budgets["analyzer"],
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
            live=True,
        )

    async def character_move(self, ctx: TurnContext) -> CharacterMove:
        out = await self.llm.json_call(
            self.character_models, prompts.character_system(ctx), prompts.character_user(ctx),
            CharacterOut, check=lambda o: check_character(o, ctx), max_tokens=400,
            budget=self.budgets["character"],
        )
        if out is None:
            return mock_character_move(ctx)
        flag = out.tactic if ctx.state.is_scam else out.green_flag
        return CharacterMove(message=out.message.strip(), flag=flag, pressure=out.pressure, live=True)
