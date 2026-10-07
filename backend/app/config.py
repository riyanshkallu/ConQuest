"""App settings, read from environment variables or backend/.env.

Nothing secret lives in code. Copy .env.example to .env and fill in keys locally;
on Render, set the same names as environment variables.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # "mock" = canned AI lines, no keys needed. "live" = real AI calls.
    ai_provider: str = "mock"

    # Empty = local SQLite file (backend/outsmart.db). On Render: the Supabase pooler connection string.
    database_url: str = ""

    # Free-tier keys. Groq: console.groq.com, Gemini: aistudio.google.com
    groq_api_key: str = ""
    gemini_api_key: str = ""

    # Models to try in order, as "provider:model". If one fails or is rate limited,
    # the next is tried, then the pre-written fallback lines.
    analyzer_models: str = "groq:openai/gpt-oss-20b,gemini:gemini-3.5-flash-lite"
    character_models: str = "groq:qwen/qwen3.8-27b,groq:openai/gpt-oss-120b,gemini:gemini-3.5-flash-lite"
    # Time budgets per role, across every model and retry, so a turn never hangs if every
    # provider is slow at once: when time runs out, the pre-written lines are used.
    analyzer_budget_seconds: float = 6.0
    character_budget_seconds: float = 10.0
    explainer_budget_seconds: float = 12.0
    generator_budget_seconds: float = 5.0

    # Scenario Generator: one call per round start, so keep it quick.
    # gpt-oss-120b first: it has its own quota and is otherwise only the character's backup.
    generator_models: str = "groq:openai/gpt-oss-120b,gemini:gemini-3.5-flash-lite,groq:openai/gpt-oss-20b"
    generator_timeout_seconds: float = 4.0
    # Explainer: one call when a round ends. Writing quality matters, so the character's models.
    explainer_models: str = "groq:qwen/qwen3.8-27b,groq:openai/gpt-oss-120b,gemini:gemini-3.5-flash-lite"
    ai_timeout_seconds: float = 8.0

    # Rate limits (protect the free AI quota). Per IP is generous: a class shares one school IP.
    players_per_ip_per_hour: int = 30
    rounds_per_player_per_hour: int = 30
    rounds_per_ip_per_hour: int = 200

    # Game tuning
    max_turns: int = 10
    scam_ratio: float = 0.65


@lru_cache
def get_settings() -> Settings:
    return Settings()
