"""Scenario Generator: invents fresh fictional names for each round so replays feel new.

Only the names change (the bank, the store, the recruiter, the cousin...). The story,
the tactics and the rules stay hand-written. Every value is checked here; if anything
is off, the round just uses the hand-written names (see LiveAI.scenario_vars).
"""

from __future__ import annotations

import json
import random
import re

from ..scenarios import PLAYER_FIRST_NAMES, Scenario, ai_var_specs, person_vars

MAX_LENGTH = 40
LETTERS = "ABCDEFGHJKLMNPRSTW"

# Real organizations and brands the game must never imitate (lowercase, whole words).
# Regional banks are here too, so the AI never lands on a real bank a player might know.
REAL_NAMES = {
    "chase", "wells fargo", "bank of america", "citi", "citibank", "capital one", "pnc", "huntington",
    "fifth third", "keybank", "key bank", "us bank", "u.s. bank", "td bank", "truist",
    "navy federal", "discover", "american express", "amex", "visa", "mastercard", "paypal", "venmo",
    "zelle", "cash app", "cashapp", "amazon", "walmart", "target", "best buy", "costco", "kroger",
    "meijer", "apple", "google", "microsoft", "netflix", "spotify", "steam", "roblox", "fortnite",
    "minecraft", "discord", "instagram", "tiktok", "snapchat", "facebook", "whatsapp", "indeed",
    "linkedin", "mcdonald's", "starbucks", "home depot", "lowe's", "fedex", "ups", "usps", "irs",
}
_REAL_NAME_RES = [re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE) for name in REAL_NAMES]


def generator_system() -> str:
    return """You invent fictional details for an educational scam-awareness game played by people of all ages around the world.
Return JSON only, with exactly the keys you are given and a short string value for each.
Rules:
- Everything must be fictional. Never use a real bank, company, store, app, game, website or famous person.
- Sound realistic and ordinary, like everyday local businesses and people. Don't tie names to any one country or region.
- For businesses, use made-up place or nature words (like "Amber Ridge" or "Tall Pines"), never a real
  city, county, region or lake name, so a name can't match a real local business.
- Each value is under 40 characters, with no digits, no web addresses and no emojis.
- Be creative: avoid the example values you are shown."""


def generator_user(scenario: Scenario, rng: random.Random) -> str:
    """Plain text, not JSON: models copy the shape of a JSON request into their answer."""
    specs = ai_var_specs(scenario)
    examples = scenario.raw.get("vars", {})
    lines = []
    for key, description in specs.items():
        # A random first letter per name, because models give the same answers every time.
        hint = f" (start it with the letter {rng.choice(LETTERS)})"
        if "full name" in description:
            hint = f" (first name starting with {rng.choice(LETTERS)}, last name starting with {rng.choice(LETTERS)})"
        lines.append(f"- {key}: {description}{hint}")
    avoid = ", ".join(str(examples[k]) for k in specs if k in examples)
    shape = json.dumps({key: "..." for key in specs})
    rules = [f"Don't reuse these examples: {avoid}."]
    if person_vars(scenario):
        rules.append(f"Don't use these first names (players use them): {', '.join(sorted(PLAYER_FIRST_NAMES))}.")
    return "\n".join(["Invent these:", *lines, *rules, f"Reply with only this JSON: {shape}"])


def check_vars(values: dict, scenario: Scenario) -> str | None:
    """Returns a problem description, or None if every value is safe to use."""
    wanted = set(ai_var_specs(scenario))
    if set(values) != wanted:
        return f"wrong keys: {sorted(set(values) ^ wanted)}"
    for key, value in values.items():
        if not isinstance(value, str) or not value.strip():
            return f"{key} is empty"
        if len(value) > MAX_LENGTH:
            return f"{key} too long"
        if re.search(r"[\d{}<>@/]|https?:|www\.|\.(com|org|net)\b", value):
            return f"{key} has digits, braces or a web address"
        for pattern in _REAL_NAME_RES:
            if pattern.search(value):
                return f"{key} uses a real name: {value!r}"
    people = [values[k].split()[0] for k in person_vars(scenario)]
    for first in people:
        if first in PLAYER_FIRST_NAMES:
            return f"name {first!r} could clash with the player's name"
    if len(set(people)) != len(people):
        return "two people share a name"
    return None
