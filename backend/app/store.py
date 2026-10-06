"""Where players and rounds live.

Players are saved to the database (db.py) on every change and cached in memory, so they
survive restarts and redeploys. Rounds in progress are kept in memory only: a restart
mid-round loses that round, nothing else. When a round ends, its summary (and messages,
if the player allows it) is saved for the playtest results.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select, update

from . import db
from .engine import RoundState
from .flags import RADAR_CATEGORIES
from .progress import Player
from .scenarios import Scenario


@dataclass
class Round:
    id: str
    player_id: str
    scenario: Scenario
    state: RoundState
    # [{"turn", "sender", "text", "links", "flag", "note", "analysis"}], in chat order
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

_PLAYER_COLUMNS = ("display_name", "hints", "save_conversations", "xp", "streak_days", "last_played",
                   "history", "badges", "verify_count", "good_call_streak")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

def save_player(player: Player) -> None:
    """Cache the player and write them (and their Scam Radar) to the database."""
    _players[player.id] = player
    values = {c: getattr(player, c) for c in _PLAYER_COLUMNS}
    with db.get_engine().begin() as conn:
        updated = conn.execute(update(db.players).where(db.players.c.id == player.id).values(**values))
        if updated.rowcount == 0:
            conn.execute(insert(db.players).values(id=player.id, created_at=_now(), **values))
        conn.execute(delete(db.radar).where(db.radar.c.player_id == player.id))
        conn.execute(insert(db.radar), [
            {"player_id": player.id, "category": c, "encountered": e, "resisted": r}
            for c, (e, r) in player.radar.items()
        ])


def get_player(player_id: str) -> Player | None:
    if player_id in _players:
        return _players[player_id]
    with db.get_engine().connect() as conn:
        row = conn.execute(select(db.players).where(db.players.c.id == player_id)).mappings().first()
        if row is None:
            return None
        radar_rows = conn.execute(select(db.radar).where(db.radar.c.player_id == player_id)).mappings()
        radar = {c: [0, 0] for c in RADAR_CATEGORIES}
        for r in radar_rows:
            if r["category"] in radar:
                radar[r["category"]] = [r["encountered"], r["resisted"]]
    player = Player(id=row["id"], radar=radar, **{c: row[c] for c in _PLAYER_COLUMNS})
    _players[player_id] = player
    return player


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------

def save_round(rnd: Round) -> None:
    _rounds[rnd.id] = rnd


def get_round(round_id: str) -> Round | None:
    return _rounds.get(round_id)


def record_finished_round(rnd: Round, save_messages: bool) -> None:
    """Save a finished round's summary, plus its messages if the player allows it."""
    state = rnd.state
    with db.get_engine().begin() as conn:
        conn.execute(insert(db.rounds).values(
            id=rnd.id, player_id=rnd.player_id, scenario_id=rnd.scenario.id, is_scam=state.is_scam,
            difficulty=state.difficulty, ending=state.ending, points=state.points, xp=rnd.xp_earned,
            turns=state.turns, mistakes=state.mistakes, details=rnd.scenario.raw.get("vars"),
            started_at=rnd.started_at, ended_at=rnd.ended_at or _now(),
        ))
        if save_messages and rnd.transcript:
            conn.execute(insert(db.messages), [
                {"round_id": rnd.id, "idx": i, "turn": m["turn"], "sender": m["sender"], "text": m["text"],
                 "flag": m.get("flag"), "analysis": m.get("analysis")}
                for i, m in enumerate(rnd.transcript)
            ])


# ---------------------------------------------------------------------------
# Health and tests
# ---------------------------------------------------------------------------

def database_ok() -> bool:
    """Used by /api/health. The keep-awake pings also stop Supabase pausing the free project."""
    try:
        with db.get_engine().connect() as conn:
            conn.execute(select(1))
        return True
    except Exception:
        return False


def clear() -> None:
    """For tests: forget everything, in memory and in the database."""
    _players.clear()
    _rounds.clear()
    with db.get_engine().begin() as conn:
        for table in reversed(db.metadata.sorted_tables):
            conn.execute(delete(table))


def forget_cache() -> None:
    """For tests: act like the server restarted (memory is gone, the database isn't)."""
    _players.clear()
    _rounds.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)
