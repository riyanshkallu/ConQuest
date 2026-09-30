"""Mock AI: keyword rules and pre-written lines. No API calls, no keys.

Used for AI_PROVIDER=mock (so the frontend can build against the API on day one) and
as the fallback when a live model fails validation or a free-tier limit is hit.
"""

from __future__ import annotations

import re

from ..engine import Analysis
from ..scenarios import render
from .base import CharacterMove, TurnContext

VERIFY_WORDS = ("back of my card", "call my bank", "call the bank", "call the number",
                "official app", "check the app", "check in the app", "call you back",
                "i'll call", "ill call", "log in myself", "check with", "call my mom",
                "call my dad", "call my parent")
CHALLENGE_WORDS = ("who is this", "who are you", "how do i know", "prove", "scam", "fake",
                   "suspicious", "not sharing", "won't", "wont", "not giving", "why do you need",
                   "no way", "don't trust", "dont trust", "never ask", "not sending",
                   "rush me", "rushing me", "pressuring me", "not falling", "nice try")
COMPLY_WORDS = ("yes", "ok", "okay", "sure", "here", "fine", "sent", "what do i do",
                "what do i need", "go ahead", "alright")

TACTIC_WORDS = {
    "urgency": ("rush", "hurry", "urgent", "pressur", "minutes", "deadline"),
    "fear": ("scare", "threat", "frozen", "freeze"),
    "authority": ("really from", "really the bank", "really my bank", "pretend", "impersonat"),
    "credential_request": ("code", "password"),
    "suspicious_link": ("link",),
    "trust_building": ("too nice", "sweet talk", "flatter"),
}
GREEN_WORDS = {
    "invites_verification": ("back of my card", "call the number", "call you"),
    "no_credentials_asked": ("didn't ask", "didnt ask", "no code", "never asked", "not asking"),
    "no_pressure": ("no rush", "not rushing", "take my time"),
    "checkable_details": ("in the app", "pending", "alert #", "alert number"),
    "official_channels": ("official app", "official website"),
}

SCAM_ESCALATE = ["authority", "urgency", "credential_request", "fear", "suspicious_link", "trust_building"]
SCAM_ON_PUSHBACK = ["trust_building", "fear", "urgency", "authority", "suspicious_link"]
LEGIT_DEFAULT = ["no_credentials_asked", "checkable_details", "no_pressure", "official_channels",
                 "invites_verification", "accepts_no"]
LEGIT_ON_PUSHBACK = ["invites_verification", "accepts_no", "official_channels", "no_credentials_asked",
                     "no_pressure", "checkable_details"]
PUSHBACK = ("challenge", "safe_verification")


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    """Whole words only, so "ok" doesn't match "look" and "here" doesn't match "where"."""
    return any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words)


def mock_analysis(ctx: TurnContext) -> Analysis:
    text = ctx.player_text.lower()
    state = ctx.state

    completion = [c.lower() for c in ctx.version.get("completion_replies", [])]
    if not state.is_scam and re.sub(r"[^a-z' ]", "", text).strip() in completion:
        return Analysis("full_compliance", 0, 10, reason="Answered the contact's question.")

    if _has(text, VERIFY_WORDS):
        a = Analysis("safe_verification", 15, -5, reason="Said they would check through an official channel.")
    elif _has(text, CHALLENGE_WORDS):
        a = Analysis("challenge", 15, -10, reason="Questioned who the contact really was.")
    elif _has_word(text, COMPLY_WORDS):
        a = Analysis("partial_compliance", -5, 10, reason="Went along with what the contact asked.")
    else:
        a = Analysis("neutral", 0, 0, reason="Kept the conversation going.")

    if state.is_scam and a.decision_type in PUSHBACK:
        for tactic, words in TACTIC_WORDS.items():
            if tactic in state.tactics_used and _has(text, words):
                a.tactic_recognized = tactic
                break
    if not state.is_scam:
        for flag, words in GREEN_WORDS.items():
            if flag in state.green_flags_shown and _has(text, words):
                a.flag_noticed = flag
                break
    return a


def mock_character_move(ctx: TurnContext) -> CharacterMove:
    state, version = ctx.state, ctx.version
    lines: dict[str, list[str]] = version["lines"]
    pushed_back = ctx.last_decision in PUSHBACK

    if state.is_scam:
        allowed = [t for t in version["allowed_tactics"] if t in lines]
        if ctx.code_just_sent and "credential_request" in allowed:
            flag = "credential_request"
        else:
            order = SCAM_ON_PUSHBACK if pushed_back else SCAM_ESCALATE
            flag = _pick(order, allowed, state.tactics_used)
        pressure = min(95, 30 + 12 * state.turns + (15 if pushed_back else 0))
        used = state.tactics_used.count(flag)
    else:
        allowed = [f for f in version["allowed_flags"] if f in lines]
        if ctx.code_just_sent and "no_credentials_asked" in allowed:
            flag = "no_credentials_asked"
        else:
            order = LEGIT_ON_PUSHBACK if pushed_back else LEGIT_DEFAULT
            shown = [e.flag_id for e in state.timeline]
            flag = _pick(order, allowed, shown)
        pressure = 0
        used = sum(1 for e in state.timeline if e.flag_id == flag)

    options = lines[flag]
    text = render(options[used % len(options)], ctx.scenario, state.id_card)
    return CharacterMove(message=text, flag=flag, pressure=pressure)


def _pick(order: list[str], allowed: list[str], used: list[str]) -> str:
    """First flag in preference order that wasn't just used and hasn't been used twice."""
    candidates = [f for f in order if f in allowed] or allowed
    last = used[-1] if used else None
    for f in candidates:
        if f != last and used.count(f) < 2:
            return f
    return min(candidates, key=used.count)


class MockAI:
    async def analyze(self, ctx: TurnContext) -> Analysis:
        return mock_analysis(ctx)

    async def character_move(self, ctx: TurnContext) -> CharacterMove:
        return mock_character_move(ctx)
