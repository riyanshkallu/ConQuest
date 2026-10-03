"""AI roles. get_ai() picks mock or live based on AI_PROVIDER."""

from functools import lru_cache

from ..config import get_settings
from .base import AIProvider
from .mock import MockAI


@lru_cache
def get_ai() -> AIProvider:
    if get_settings().ai_provider == "live":
        from .live import LiveAI  # imported lazily so mock mode needs no AI packages or keys
        return LiveAI(get_settings())
    return MockAI()
