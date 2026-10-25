"""Where players and rounds live.

Players and rounds in progress are saved to the database (db.py) on every change and
cached in memory, so they survive restarts and redeploys (Render's free plan also restarts
the server after it sleeps). When a round ends, its summary (and messages, if the player
allows it) is saved to the database.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select, update

from . import db, schemas
from .config import get_settings
from .engine import IdCard, RoundState, ScoreEvent, TimelineEvent
from .flags import RADAR_CATEGORIES
from .progress import Player
from .scenarios import Scenario

log = logging.getLogger(__name__)

# Saved rounds older than this are deleted. Long enough to finish a round and read the result.
LIVE_ROUND_DAYS = 2


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
    ai_live: int = 0       # analyzer + character answers written by a live model
    ai_fallback: int = 0   # ... and by the fallback rules / pre-written lines
    coach_given: set[str] = field(default_factory=set)  # coaching tips already shown this round
    demo: bool = False  # recorded for the video; marked as demo when the round is saved
    last_contact_at: float | None = None  # when the contact's latest message was sent (monotonic)
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
    """Cache the round and write it to the database. Called after every change to it."""
    _rounds[rnd.id] = rnd
    values = {"data": _round_to_json(rnd), "updated_at": _now()}
    with db.get_engine().begin() as conn:
        updated = conn.execute(update(db.live_rounds).where(db.live_rounds.c.id == rnd.id).values(**values))
        if updated.rowcount == 0:  # a new round: also clear out old ones
            conn.execute(insert(db.live_rounds).values(id=rnd.id, **values))
            cutoff = _now() - timedelta(days=LIVE_ROUND_DAYS)
            conn.execute(delete(db.live_rounds).where(db.live_rounds.c.updated_at < cutoff))


def get_round(round_id: str) -> Round | None:
    if round_id in _rounds:
        return _rounds[round_id]
    with db.get_engine().connect() as conn:
        row = conn.execute(select(db.live_rounds.c.data).where(db.live_rounds.c.id == round_id)).first()
    if row is None:
        return None
    try:
        rnd = _round_from_json(row.data)
    except (KeyError, TypeError, ValueError):  # saved by an older version that no longer fits
        log.warning("could not load saved round %s", round_id, exc_info=True)
        return None
    _rounds[round_id] = rnd
    return rnd


def _round_to_json(rnd: Round) -> dict:
    return {
        "id": rnd.id, "player_id": rnd.player_id,
        "scenario": {"id": rnd.scenario.id, "raw": rnd.scenario.raw},
        "state": asdict(rnd.state), "transcript": rnd.transcript,
        "started_at": rnd.started_at.isoformat(),
        "ended_at": rnd.ended_at.isoformat() if rnd.ended_at else None,
        "xp_earned": rnd.xp_earned, "new_badges": rnd.new_badges, "finalized": rnd.finalized,
        "code_sent": rnd.code_sent, "ai_live": rnd.ai_live, "ai_fallback": rnd.ai_fallback,
        "coach_given": sorted(rnd.coach_given), "demo": rnd.demo,
        "result": rnd.result.model_dump(mode="json") if rnd.result is not None else None,
    }


def _known(cls, data: dict) -> dict:
    """Only the keys the dataclass still has, so a field removed in a later version is ignored."""
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


def _round_from_json(data: dict) -> Round:
    state = dict(data["state"])
    state["id_card"] = IdCard(**_known(IdCard, state["id_card"]))
    state["timeline"] = [TimelineEvent(**_known(TimelineEvent, e)) for e in state.get("timeline", [])]
    state["score"] = [ScoreEvent(**_known(ScoreEvent, e)) for e in state.get("score", [])]
    return Round(
        id=data["id"], player_id=data["player_id"],
        scenario=Scenario(data["scenario"]["id"], data["scenario"]["raw"]),
        state=RoundState(**_known(RoundState, state)), transcript=data["transcript"],
        started_at=datetime.fromisoformat(data["started_at"]),
        ended_at=datetime.fromisoformat(data["ended_at"]) if data.get("ended_at") else None,
        xp_earned=data.get("xp_earned", 0), new_badges=data.get("new_badges", []),
        finalized=data.get("finalized", False), code_sent=data.get("code_sent", False),
        ai_live=data.get("ai_live", 0), ai_fallback=data.get("ai_fallback", 0),
        coach_given=set(data.get("coach_given", [])), demo=data.get("demo", False),
        result=schemas.ResultResponse.model_validate(data["result"]) if data.get("result") else None,
        # last_contact_at is a clock reading from the old process, so it isn't kept.
    )


def last_scenario_id(player_id: str) -> str | None:
    """The scenario of the player's most recent round on this server (for Surprise me)."""
    rounds = [r for r in _rounds.values() if r.player_id == player_id]
    return max(rounds, key=lambda r: r.started_at).scenario.id if rounds else None


def record_finished_round(rnd: Round, save_messages: bool) -> None:
    """Save a finished round's summary, plus its messages if the player allows it."""
    state = rnd.state
    with db.get_engine().begin() as conn:
        conn.execute(insert(db.rounds).values(
            id=rnd.id, player_id=rnd.player_id, scenario_id=rnd.scenario.id, is_scam=state.is_scam,
            difficulty=state.difficulty, ending=state.ending, points=state.points, xp=rnd.xp_earned,
            turns=state.turns, mistakes=state.mistakes,
            details={**rnd.scenario.raw.get("vars", {}), **({"demo": True} if rnd.demo else {})},
            started_at=rnd.started_at, ended_at=rnd.ended_at or _now(),
        ))
        conn.execute(insert(db.round_ai).values(round_id=rnd.id, live=rnd.ai_live, fallback=rnd.ai_fallback))
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
    """For tests: forget everything, in memory and in the database.

    Only runs on a test database. A script that leaves DATABASE_URL unset still picks up the
    real Supabase from .env, and this would delete every player and saved round there.
    """
    url = get_settings().database_url
    if url != "sqlite://" and url != (os.environ.get("TEST_DATABASE_URL") or None):
        raise RuntimeError("store.clear() deletes every row, so it only runs on a test database: "
                           "in-memory SQLite (DATABASE_URL=sqlite://) or TEST_DATABASE_URL.")
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
