"""Rate limits that protect the free AI quota.

Every round costs about 20 free AI calls, so one person (or a bot) starting rounds in a loop
could use up the day's quota before judges play. This keeps a short history of recent
requests per key in memory: fine because Render runs one process, and a restart just
forgets the history.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable

MAX_KEYS = 10_000  # forget idle keys past this, so memory can't grow without limit


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, limit: int, seconds: float) -> float | None:
        """Record a request. Returns None if allowed, or how many seconds until it would be."""
        now = self._clock()
        hits = self._hits[key]
        while hits and hits[0] <= now - seconds:
            hits.popleft()
        if len(hits) >= limit:
            return hits[0] + seconds - now
        hits.append(now)
        if len(self._hits) > MAX_KEYS:
            for k in [k for k, q in self._hits.items() if not q]:
                del self._hits[k]
        return None

    def clear(self) -> None:
        self._hits.clear()


limiter = RateLimiter()
