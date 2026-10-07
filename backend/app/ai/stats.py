"""How often the AI answered live vs fell back to pre-written lines, since the server started.

Shown in /api/health, so you can spot a free-tier limit being hit (fallbacks climbing)
before a playtest or while judges are playing.
"""

from __future__ import annotations

from collections import Counter

ROLES = ("generator", "analyzer", "character", "explainer")
_counts: Counter[tuple[str, bool]] = Counter()


def record(role: str, live: bool) -> None:
    _counts[(role, live)] += 1


def snapshot() -> dict:
    by_role = {role: {"live": _counts[(role, True)], "fallback": _counts[(role, False)]} for role in ROLES}
    return {
        "live": sum(r["live"] for r in by_role.values()),
        "fallback": sum(r["fallback"] for r in by_role.values()),
        "by_role": by_role,
    }


def reset() -> None:
    _counts.clear()
