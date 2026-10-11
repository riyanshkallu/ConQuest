"""Database connection and tables.

DATABASE_URL picks the database:
  (empty)                        -> backend/outsmart.db, a SQLite file for local development
  sqlite://                      -> in memory, for tests
  postgresql://...supabase...    -> Supabase in production (use the pooler connection string)

The four tables follow the plan, plus small ones for AI stats and rounds in progress. No real names, emails or phone numbers are stored, and
messages are only saved when the player leaves "save conversations" on.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import (JSON, Boolean, Column, Date, DateTime, Engine, ForeignKey, Integer, MetaData, String,
                        Table, Text, create_engine, text)
from sqlalchemy.pool import StaticPool

from .config import BACKEND_DIR, get_settings

metadata = MetaData()

players = Table(
    "players", metadata,
    Column("id", String(20), primary_key=True),
    Column("display_name", String(30)),
    Column("hints", Boolean, nullable=False),
    Column("save_conversations", Boolean, nullable=False),
    Column("xp", Integer, nullable=False),
    Column("streak_days", Integer, nullable=False),
    Column("last_played", Date),
    Column("history", JSON, nullable=False),        # is_scam of each finished round, oldest first
    Column("badges", JSON, nullable=False),
    Column("verify_count", Integer, nullable=False),
    Column("good_call_streak", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

radar = Table(
    "radar", metadata,
    Column("player_id", String(20), ForeignKey("players.id", ondelete="CASCADE"), primary_key=True),
    Column("category", String(30), primary_key=True),  # Scam Radar row, e.g. "urgency"
    Column("encountered", Integer, nullable=False),
    Column("resisted", Integer, nullable=False),
)

rounds = Table(
    "rounds", metadata,
    Column("id", String(20), primary_key=True),
    Column("player_id", String(20), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("scenario_id", String(40), nullable=False),
    Column("is_scam", Boolean, nullable=False),
    Column("difficulty", Integer, nullable=False),
    Column("ending", String(20), nullable=False),
    Column("points", Integer, nullable=False),
    Column("xp", Integer, nullable=False),
    Column("turns", Integer, nullable=False),
    Column("mistakes", Integer, nullable=False),
    Column("details", JSON),                         # this round's generated names and numbers
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("ended_at", DateTime(timezone=True), nullable=False),
)

# How many of the round's AI answers came from a live model vs the fallback lines.
# Its own table (not new columns on rounds) so existing Supabase tables need no change.
round_ai = Table(
    "round_ai", metadata,
    Column("round_id", String(20), ForeignKey("rounds.id", ondelete="CASCADE"), primary_key=True),
    Column("live", Integer, nullable=False),
    Column("fallback", Integer, nullable=False),
)

messages = Table(
    "messages", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("round_id", String(20), ForeignKey("rounds.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("idx", Integer, nullable=False),          # position in the chat
    Column("turn", Integer, nullable=False),
    Column("sender", String(20), nullable=False),    # contact, player or notification
    Column("text", Text, nullable=False),
    Column("flag", String(40)),                      # tactic or green flag on contact messages
    Column("analysis", JSON),                        # the analyzer's judgment of player messages
)

# Rounds in progress, saved after every turn so a restart (Render's free plan sleeps when
# idle, and every deploy restarts it) doesn't lose the round the player is in.
live_rounds = Table(
    "live_rounds", metadata,
    Column("id", String(20), primary_key=True),
    Column("data", JSON, nullable=False),             # the whole round: state, transcript, result
    Column("updated_at", DateTime(timezone=True), nullable=False, index=True),
)


def make_engine(url: str) -> Engine:
    if not url:
        url = f"sqlite:///{BACKEND_DIR / 'outsmart.db'}"
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    if url == "sqlite://":  # in memory: every connection must share the same database
        return create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # Supabase's connection pooler doesn't support prepared statements, so turn them off.
    # pre_ping replaces connections the pooler closed while the app was idle.
    return create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2,
                         connect_args={"prepare_threshold": None})


def create_tables(engine: Engine) -> None:
    metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        # Supabase also exposes tables through a public web API. Row level security with no
        # policies switches that off. The app connects as the tables' owner, so it isn't affected.
        with engine.begin() as conn:
            for table in metadata.sorted_tables:
                conn.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))


@lru_cache
def get_engine() -> Engine:
    engine = make_engine(get_settings().database_url)
    create_tables(engine)
    return engine
