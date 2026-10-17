"""What every AI provider (mock or live) takes in and hands back."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..engine import Analysis, IdCard, RoundState
from ..scenarios import Scenario


@dataclass
class CharacterMove:
    message: str
    flag: str | None  # red tactic (scam) or green flag (legit) this message shows
    pressure: int = 0
    live: bool = False  # True when a live AI model wrote this (not a pre-written line)


@dataclass
class TurnContext:
    scenario: Scenario
    state: RoundState
    transcript: list[dict] = field(default_factory=list)  # [{"sender": ..., "text": ...}]
    player_text: str = ""
    last_decision: str = "neutral"
    code_just_sent: bool = False  # the one-time code arrives alongside this reply
    code_arrived: bool = False    # the player has the code by now (earlier, or with this reply)

    @property
    def version(self) -> dict:
        return self.scenario.version(self.state.is_scam)


@dataclass
class ExplainRequest:
    """What the Explainer sees at the end of a round. The facts here are already decided."""
    is_scam: bool
    ending_title: str
    contact_name: str
    id_card: IdCard
    messages: list[dict]            # [{"index", "sender", "text", "flag"}] in chat order
    flags: list[str]                # one flag id per timeline card


@dataclass
class ExplainerText:
    """The Explainer's wording. Anything missing falls back to the engine's text."""
    timeline: dict[str, str] = field(default_factory=dict)   # flag id -> sentence
    messages: dict[int, str] = field(default_factory=dict)   # transcript index -> sentence


class AIProvider(Protocol):
    async def analyze(self, ctx: TurnContext) -> Analysis: ...

    async def character_move(self, ctx: TurnContext) -> CharacterMove: ...

    async def scenario_vars(self, scenario: Scenario) -> dict[str, str] | None:
        """Fresh fictional names for one round, or None to use the hand-written ones."""
        ...

    async def explain(self, request: ExplainRequest) -> ExplainerText | None:
        """Friendlier, conversation-specific wording for the result, or None for the engine's text."""
        ...
