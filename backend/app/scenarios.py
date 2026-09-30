"""Loads the hand-written scenario seeds and builds a fictional ID card for each round.

Each file in data/scenarios/ is one *pair*: a scam version and a legit version that
start almost the same way. Text can use {placeholders}. They're filled in from the
scenario's "vars" plus the round's ID card, via render().
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from functools import lru_cache

from .config import BACKEND_DIR
from .engine import IdCard

SCENARIO_DIR = BACKEND_DIR / "data" / "scenarios"


@dataclass
class Scenario:
    id: str
    raw: dict

    @property
    def title(self) -> str:
        return self.raw["title"]

    @property
    def channel(self) -> str:
        return self.raw["channel"]

    @property
    def difficulty(self) -> int:
        return self.raw["difficulty"]

    def version(self, is_scam: bool) -> dict:
        return self.raw["scam" if is_scam else "legit"]


@lru_cache
def load_scenarios() -> dict[str, Scenario]:
    scenarios = {}
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        scenarios[raw["id"]] = Scenario(raw["id"], raw)
    return scenarios


def get_scenario(scenario_id: str) -> Scenario | None:
    return load_scenarios().get(scenario_id)


class _Blank(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"  # leave unknown placeholders visible instead of crashing


def render(text: str, scenario: Scenario, card: IdCard) -> str:
    values = _Blank(scenario.raw.get("vars", {}))
    values.update(
        name=card.name,
        first_name=card.name.split()[0],
        email=card.email,
        last4=card.card_last4,
        code=card.verification_code,
    )
    return text.format_map(values)


# ---------------------------------------------------------------------------
# Fictional ID cards
# ---------------------------------------------------------------------------

_FIRST = ["Jordan", "Avery", "Riley", "Morgan", "Casey", "Taylor", "Jamie", "Quinn", "Drew", "Sam"]
_LAST = ["Rivera", "Patel", "Nguyen", "Brooks", "Kim", "Okafor", "Lopez", "Walsh", "Chen", "Hayes"]
_PASSWORDS = ["Sunflower#27", "BlueTiger!88", "Maple$Road14", "Comet@2031"]


def _luhn_check_digit(partial: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(partial)):
        d = int(ch)
        if i % 2 == 0:  # these positions get doubled once the check digit is appended
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return str((10 - total % 10) % 10)


def new_id_card(scenario: Scenario, rng: random.Random) -> IdCard:
    first, last = rng.choice(_FIRST), rng.choice(_LAST)
    partial = "400000" + "".join(rng.choice("0123456789") for _ in range(9))
    card = partial + _luhn_check_digit(partial)
    return IdCard(
        name=f"{first} {last}",
        email=f"{first.lower()}.{last.lower()}@mail.example",
        phone=f"(614) 555-01{rng.randint(0, 99):02d}",  # 555-01xx is reserved for fiction
        bank=scenario.raw.get("vars", {}).get("bank", "Buckeye Federal Credit Union"),
        card_number=" ".join(card[i:i + 4] for i in range(0, 16, 4)),
        verification_code=f"{rng.randint(0, 999999):06d}",
        password=rng.choice(_PASSWORDS) if scenario.raw.get("uses_password") else None,
        gift_card_code=_gift_code(rng) if scenario.raw.get("uses_gift_card") else None,
        gaming_username=f"{first.lower()}_builds" if scenario.raw.get("uses_gaming_account") else None,
    )


def _gift_code(rng: random.Random) -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(rng.choice(chars) for _ in range(4)) for _ in range(3))
