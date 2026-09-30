"""What every AI provider (mock or live) takes in and hands back."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..engine import Analysis, RoundState
from ..scenarios import Scenario


@dataclass
class CharacterMove:
    message: str
    flag: str | None  # red tactic (scam) or green flag (legit) this message shows
    pressure: int = 0


@dataclass
class TurnContext:
    scenario: Scenario
    state: RoundState
    transcript: list[dict] = field(default_factory=list)  # [{"sender": ..., "text": ...}]
    player_text: str = ""
    last_decision: str = "neutral"
    code_just_sent: bool = False  # the one-time code arrives alongside this reply

    @property
    def version(self) -> dict:
        return self.scenario.version(self.state.is_scam)


class AIProvider(Protocol):
    async def analyze(self, ctx: TurnContext) -> Analysis: ...

    async def character_move(self, ctx: TurnContext) -> CharacterMove: ...
