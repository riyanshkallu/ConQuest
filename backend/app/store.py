"""Where players and rounds live.

In-memory for now: everything resets when the server restarts. Planned for Oct 9:
players/rounds/messages/radar tables in Supabase (SQLite locally). Only this file should
need to change for that.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .engine import RoundState
from .progress import Player
from .scenarios import Scenario


@dataclass
class Round:
    id: str
    player_id: str
    scenario: Scenario
    state: RoundState
    # [{"turn", "sender", "text", "links", "flag", "note"}], in chat order
    transcript: list[dict] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    xp_earned: int = 0
    new_badges: list[str] = field(default_factory=list)
    finalized: bool = False
    code_sent: bool = False
    result: object | None = None  # cached ResultResponse, so the Explainer runs once per round
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


_players: dict[str, Player] = {}
_rounds: dict[str, Round] = {}


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def save_player(player: Player) -> None:
    _players[player.id] = player


def get_player(player_id: str) -> Player | None:
    return _players.get(player_id)


def save_round(rnd: Round) -> None:
    _rounds[rnd.id] = rnd


def get_round(round_id: str) -> Round | None:
    return _rounds.get(round_id)


def clear() -> None:
    """For tests."""
    _players.clear()
    _rounds.clear()
