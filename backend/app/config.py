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

    # Free-tier keys. Groq: console.groq.com, Gemini: aistudio.google.com
    groq_api_key: str = ""
    gemini_api_key: str = ""

    # Models to try in order, as "provider:model". If one fails or is rate limited,
    # the next is tried, then the pre-written fallback lines.
    analyzer_models: str = "groq:openai/gpt-oss-20b,gemini:gemini-3.5-flash-lite"
    character_models: str = "groq:qwen/qwen3.8-27b,groq:openai/gpt-oss-120b,gemini:gemini-3.5-flash-lite"
    # Scenario Generator: one call per round start, so keep it quick.
    # Gemini first: its quota is separate from the analyzer's Groq model.
    generator_models: str = "gemini:gemini-3.5-flash-lite,groq:openai/gpt-oss-20b"
    generator_timeout_seconds: float = 4.0
    ai_timeout_seconds: float = 8.0

    # Game tuning
    max_turns: int = 10
    scam_ratio: float = 0.65


@lru_cache
def get_settings() -> Settings:
    return Settings()
