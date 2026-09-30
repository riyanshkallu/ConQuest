"""Calls free-tier LLMs and returns validated JSON, or None so the caller can fall back.

Groq and Gemini both accept OpenAI-style requests, so one SDK talks to both; only the
base URL and key differ. Models are tried in the order given in settings. A provider
that returns 429 (free-tier limit hit) is skipped for a short cooldown so players don't
wait on it every turn.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable, TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from ..config import Settings

log = logging.getLogger("outsmart.ai")
T = TypeVar("T", bound=BaseModel)

PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "groq_api_key"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini_api_key"),
}
RATE_LIMIT_COOLDOWN_SECONDS = 20


def parse_models(spec: str) -> list[tuple[str, str]]:
    """'groq:llama-3.1-8b-instant,gemini:gemini-2.5-flash' -> [('groq', ...), ('gemini', ...)]"""
    pairs = []
    for item in spec.split(","):
        provider, _, model = item.strip().partition(":")
        if provider in PROVIDERS and model:
            pairs.append((provider, model))
    return pairs


def _extract_json(text: str) -> str:
    """Some models wrap JSON in ```json fences or add a sentence around it."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group() if match else text


class LLM:
    def __init__(self, settings: Settings):
        self.timeout = settings.ai_timeout_seconds
        self.clients: dict[str, AsyncOpenAI] = {}
        for name, (url, key_attr) in PROVIDERS.items():
            key = getattr(settings, key_attr)
            if key:
                self.clients[name] = AsyncOpenAI(api_key=key, base_url=url, max_retries=0)
        self._cooldown_until: dict[str, float] = {}

    async def json_call(
        self,
        models: list[tuple[str, str]],
        system: str,
        user: str,
        schema: type[T],
        check: Callable[[T], str | None] | None = None,
        max_tokens: int = 300,
    ) -> T | None:
        """Return the first reply that parses into `schema` and passes `check`.

        API errors move on to the next model. A reply that fails validation is
        regenerated once; if that also fails, return None (the caller uses a fallback).
        """
        for provider, model in models:
            client = self.clients.get(provider)
            if client is None or time.monotonic() < self._cooldown_until.get(provider, 0):
                continue
            for attempt in (1, 2):
                started = time.monotonic()
                try:
                    resp = await client.chat.completions.create(
                        model=model,
                        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                        response_format={"type": "json_object"},
                        temperature=0.8,
                        max_tokens=max_tokens,
                        timeout=self.timeout,
                    )
                except openai.RateLimitError:
                    log.warning("%s rate limited, cooling down", provider)
                    self._cooldown_until[provider] = time.monotonic() + RATE_LIMIT_COOLDOWN_SECONDS
                    break
                except openai.OpenAIError as exc:
                    log.warning("%s:%s failed: %s", provider, model, exc)
                    break

                text = resp.choices[0].message.content or ""
                elapsed = time.monotonic() - started
                try:
                    obj = schema.model_validate_json(_extract_json(text))
                except (ValidationError, json.JSONDecodeError) as exc:
                    problem = f"invalid JSON: {exc.errors()[0]['msg'] if isinstance(exc, ValidationError) else exc}"
                else:
                    problem = check(obj) if check else None
                    if problem is None:
                        log.info("%s:%s ok in %.1fs", provider, model, elapsed)
                        return obj
                log.warning("%s:%s attempt %d rejected (%s): %r", provider, model, attempt, problem, text[:200])
            else:
                return None  # two bad replies: use the fallback line rather than make the player wait longer
        return None
