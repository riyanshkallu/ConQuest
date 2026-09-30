"""The game engine: hidden state, rule checks, points and endings.

This module is the only thing that decides how a round ends. It has no web code and
no AI code, so every rule can be tested on its own (see tests/test_engine.py).

The AI's job is to *talk*. The analyzer's output comes in here as an `Analysis`, and
the engine decides what it means. Claims the AI makes (like "the player spotted
urgency") only count if they check out against what actually happened.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from .flags import ALL_FLAGS, GREEN_FLAGS, RED_FLAGS

# ---------------------------------------------------------------------------
# Tuning numbers (from the plan's tables)
# ---------------------------------------------------------------------------

MINOR_INFO_RISK = 20
LINK_RISK = 25
PAYMENT_RISK = 40
ASK_PROOF_SUSPICION = 15
LEGIT_MAX_PRESSURE = 10

POINTS_VERIFY = 30
POINTS_SPOT = 10
POINTS_CORRECT_REPORT = 25
POINTS_REFUSE = 15
POINTS_MINOR_INFO = -10
POINTS_SENSITIVE_TO_LEGIT = -20
POINTS_FALSE_ALARM = -15
POINTS_PER_TURN_UNDER_PAR = 5
COMPLETION_BONUS_XP = 20

MAX_LEGIT_IN_A_ROW = 2

DECISION_TYPES = {
    "safe_verification", "challenge", "neutral",
    "partial_compliance", "full_compliance", "off_topic",
}
# Character tactics that count as "asking for something". Pushing back right after one
# earns the refusal bonus.
REQUEST_TACTICS = {"credential_request", "financial_pressure", "unusual_payment"}

ENDINGS: dict[str, tuple[str, str, bool]] = {
    # code: (title, message, is_scam)
    "OUTSMARTED": ("Outsmarted", "You recognized the scam and avoided every trap.", True),
    "ESCAPED": ("Escaped", "You made some mistakes but protected yourself in the end.", True),
    "ALMOST_SCAMMED": ("Almost Scammed", "You avoided the final trap but gave away information a scammer could use later.", True),
    "SCAMMED": ("Scammed", "The scammer got what they wanted.", True),
    "SMART_AND_SAFE": ("Smart and Safe", "You checked before trusting. That works every time.", False),
    "LUCKY": ("Lucky", "It was real this time. The same move against the scam version would have cost you.", False),
    "FALSE_ALARM": ("False Alarm", "This was a real contact. Here is what showed it was genuine.", False),
}
PAR_BONUS_ENDINGS = {"OUTSMARTED", "ESCAPED", "SMART_AND_SAFE"}
ESCAPED_CLEAN_MESSAGE = ("You got out safely. To fully outsmart them, verify independently "
                         "or call out the trick they were using.")


def ending_message(state: RoundState) -> str:
    """The ending's message, with a variant for escaping without any mistakes."""
    if state.ending == "ESCAPED" and state.mistakes == 0 and not state.info_shared:
        return ESCAPED_CLEAN_MESSAGE
    return ENDINGS[state.ending][1]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class IdCard:
    """The fictional identity the player uses for one round."""
    name: str
    email: str
    phone: str
    bank: str
    card_number: str
    verification_code: str  # arrives mid-game as a notification, not shown on the card
    password: str | None = None
    gift_card_code: str | None = None
    gaming_username: str | None = None

    def trap_items(self) -> dict[str, str]:
        """Items a scammer is after. Typing one in a scam round ends it as SCAMMED."""
        items = {"one-time code": self.verification_code, "full card number": self.card_number}
        if self.password:
            items["password"] = self.password
        if self.gift_card_code:
            items["gift card code"] = self.gift_card_code
        return items

    @property
    def card_last4(self) -> str:
        return _digits(self.card_number)[-4:]


@dataclass
class Analysis:
    """The Player Analyzer's judgment of one reply, after schema validation."""
    decision_type: str = "neutral"
    suspicion_change: int = 0
    trust_change: int = 0
    tactic_recognized: str | None = None
    flag_noticed: str | None = None
    mistake: bool = False
    reason: str = ""


@dataclass
class TimelineEvent:
    """One red or green flag the contact showed, and how the player responded."""
    turn: int
    flag_id: str
    response: str = "no_response"  # red: resisted/fell_for_it/no_response, green: noticed/missed


@dataclass
class ScoreEvent:
    label: str
    points: int


@dataclass
class RoundState:
    is_scam: bool
    id_card: IdCard
    objective: str  # scam: what they're after. legit: the real reason for contact
    objective_is_payment: bool = False
    max_turns: int = 10
    par_turns: int = 6

    suspicion: int = 0
    trust: int = 50
    risk: int = 0
    pressure: int = 0
    mistakes: int = 0
    turns: int = 0

    info_shared: list[str] = field(default_factory=list)       # minor items, e.g. "email"
    sensitive_shared: list[str] = field(default_factory=list)  # trap items given to a legit contact
    tactics_used: list[str] = field(default_factory=list)      # red flags the scammer used
    green_flags_shown: list[str] = field(default_factory=list)
    recognized: list[str] = field(default_factory=list)        # red flags the player called out
    noticed: list[str] = field(default_factory=list)           # green flags the player noticed
    timeline: list[TimelineEvent] = field(default_factory=list)
    score: list[ScoreEvent] = field(default_factory=list)
    links_opened: list[str] = field(default_factory=list)
    verified: bool = False
    ending: str | None = None

    @property
    def ended(self) -> bool:
        return self.ending is not None

    @property
    def points(self) -> int:
        return max(0, sum(e.points for e in self.score))


# ---------------------------------------------------------------------------
# Round setup
# ---------------------------------------------------------------------------

def assign_is_scam(history: list[bool], rng: random.Random, scam_ratio: float = 0.65) -> bool:
    """Pick scam or legit for a new round.

    history: is_scam for the player's past rounds, oldest first.
    A new player's first round is always a scam, and there are never more than two
    legit rounds in a row.
    """
    if not history:
        return True
    recent = history[-MAX_LEGIT_IN_A_ROW:]
    if len(recent) == MAX_LEGIT_IN_A_ROW and not any(recent):
        return True
    return rng.random() < scam_ratio


# ---------------------------------------------------------------------------
# Text checks: real personal data, trap items, minor info
# ---------------------------------------------------------------------------

_NUMBER_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_NUMBER_WORD_RE = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE)
# A run of digits that may be split by spaces, commas, dashes, dots or brackets:
# "482 913", "four eight two, nine one three", "(555) 010-3382"
_DIGIT_RUN_RE = re.compile(r"\d(?:[\d\s().,-]*\d)?")
# The 555-0100 to 555-0199 range is reserved for fiction, so these are always allowed.
_FICTIONAL_PHONE_RE = re.compile(r"^1?\d{3}55501\d{2}$")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _spell_digits(text: str) -> str:
    """'four eight two' -> '4 8 2', so spelled-out codes are caught too."""
    return _NUMBER_WORD_RE.sub(lambda m: _NUMBER_WORDS[m.group(1).lower()], text)


def digit_runs(text: str) -> list[str]:
    """Every number in the text with its separators removed."""
    return [_digits(m.group()) for m in _DIGIT_RUN_RE.finditer(_spell_digits(text))]


def _luhn_ok(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def blocked_reason(text: str, card: IdCard) -> str | None:
    """If the text looks like real personal data, return why. Otherwise None.

    ID card values are always allowed, so typing the fictional card number is treated
    as a trap (handled by find_trap_items), not blocked.
    """
    allowed = [_digits(card.card_number), _digits(card.phone), card.verification_code]
    for run in digit_runs(text):
        for value in allowed:  # "4417 482913" is last-4 + code, not one 10-digit number
            run = run.replace(value, "")
        if len(run) == 9 and run[:3] not in {"000", "666"} and not run.startswith("9"):
            return "That looks like a real Social Security number. Only use details from your ID card."
        if 13 <= len(run) <= 19 and _luhn_ok(run):
            return "That looks like a real card number. Only use details from your ID card."
        if len(run) in (10, 11) and (len(run) == 10 or run.startswith("1")):
            if not _FICTIONAL_PHONE_RE.match(run):
                return "That looks like a real phone number. Only use details from your ID card."
    return None


def find_trap_items(text: str, card: IdCard) -> list[str]:
    """Names of the trap items that appear in the text, e.g. ['one-time code']."""
    runs = digit_runs(text)
    found = []
    for name, value in card.trap_items().items():
        digits = _digits(value)
        if name in ("one-time code", "full card number"):
            if any(digits in run for run in runs):
                found.append(name)
        elif _alnum(value) and _alnum(value) in _alnum(text):
            found.append(name)
    return found


def find_minor_info(text: str, card: IdCard) -> list[str]:
    """Less sensitive ID card details that appear in the text, e.g. ['email']."""
    runs = digit_runs(text)
    lowered = text.lower()
    found = []
    if card.email.lower() in lowered:
        found.append("email")
    if _digits(card.phone) in runs or _digits(card.phone)[-7:] in runs:
        found.append("phone number")
    if card.card_last4 in runs:
        found.append("card's last four digits")
    if card.gaming_username and card.gaming_username.lower() in lowered:
        found.append("gaming username")
    return found


# ---------------------------------------------------------------------------
# A player turn
# ---------------------------------------------------------------------------

@dataclass
class PreCheck:
    """What the fixed rule checks found in a reply, before the AI analyzer runs."""
    traps: list[str]
    minor: list[str]


def begin_turn(state: RoundState, text: str) -> PreCheck:
    """Run the fixed checks on a reply that already passed blocked_reason().

    Counts the turn, records anything shared, and ends a scam round as SCAMMED if a
    trap item was typed. The caller should skip the analyzer if state.ended.
    """
    _require_active(state)
    state.turns += 1
    traps = find_trap_items(text, state.id_card)
    minor = find_minor_info(text, state.id_card)

    for item in minor:
        if item in state.info_shared:
            continue  # still a mistake this turn, but the points penalty applies once
        state.info_shared.append(item)
        state.risk = _clamp(state.risk + MINOR_INFO_RISK)
        state.score.append(ScoreEvent(f"Shared your {item}", POINTS_MINOR_INFO))

    if traps and state.is_scam:
        _resolve_pending(state, fell_for_it=True)
        _finish(state, "SCAMMED")
    elif traps:
        new = [t for t in traps if t not in state.sensitive_shared]
        for item in new:
            state.sensitive_shared.append(item)
            state.score.append(ScoreEvent(f"Shared your {item} (a real contact never needs it)",
                                          POINTS_SENSITIVE_TO_LEGIT))
    return PreCheck(traps=traps, minor=minor)


def apply_analysis(state: RoundState, analysis: Analysis, pre: PreCheck) -> str | None:
    """Apply the analyzer's judgment, then check for endings. Returns the ending code if the round ended."""
    _require_active(state)
    state.suspicion = _clamp(state.suspicion + analysis.suspicion_change)
    state.trust = _clamp(state.trust + analysis.trust_change)

    complied = analysis.decision_type in ("partial_compliance", "full_compliance")
    made_mistake = analysis.mistake or bool(pre.minor) or bool(pre.traps)
    if state.is_scam and complied:
        made_mistake = True  # going along with a scammer is always a mistake
    if made_mistake:
        state.mistakes += 1

    # Refusal bonus: pushing back right after the contact asked for a code or money.
    pushed_back = analysis.decision_type in ("challenge", "safe_verification")
    last_request = _last_pending_request(state)
    if pushed_back and last_request:
        label = RED_FLAGS[last_request].label.lower()
        state.score.append(ScoreEvent(f"Refused a {label}", POINTS_REFUSE))

    _resolve_pending(state, fell_for_it=made_mistake)

    # Only count a spotted flag if the contact really showed it.
    t = analysis.tactic_recognized
    if t in RED_FLAGS and t in state.tactics_used and t not in state.recognized:
        state.recognized.append(t)
        state.score.append(ScoreEvent(f"Spotted: {RED_FLAGS[t].label}", POINTS_SPOT))
    g = analysis.flag_noticed
    if g in GREEN_FLAGS and g in state.green_flags_shown and g not in state.noticed:
        state.noticed.append(g)
        state.score.append(ScoreEvent(f"Noticed: {GREEN_FLAGS[g].label}", POINTS_SPOT))

    if analysis.decision_type == "full_compliance":
        if state.is_scam:
            if state.objective_is_payment:
                state.risk = _clamp(state.risk + PAYMENT_RISK)
            return _finish(state, "SCAMMED")
        return _finish(state, _legit_trust_ending(state))

    if state.turns >= state.max_turns:
        return _finish(state, _turn_limit_ending(state))
    return None


def record_character_move(state: RoundState, flag_id: str | None, pressure: int = 0) -> None:
    """Log the flag the contact's latest message showed (a tactic or a green flag)."""
    _require_active(state)
    if state.is_scam:
        state.pressure = _clamp(pressure)
        if flag_id in RED_FLAGS:
            state.tactics_used.append(flag_id)
            state.timeline.append(TimelineEvent(state.turns, flag_id))
    else:
        state.pressure = min(_clamp(pressure), LEGIT_MAX_PRESSURE)
        if flag_id in GREEN_FLAGS:
            if flag_id not in state.green_flags_shown:
                state.green_flags_shown.append(flag_id)
            state.timeline.append(TimelineEvent(state.turns, flag_id, "missed"))


def ask_proof_analysis() -> Analysis:
    """The Ask for proof button is a known challenge, so it skips the AI analyzer."""
    return Analysis(decision_type="challenge", suspicion_change=ASK_PROOF_SUSPICION,
                    trust_change=-5, reason="Asked the contact to prove who they are.")


# ---------------------------------------------------------------------------
# Action buttons
# ---------------------------------------------------------------------------

ENDING_ACTIONS = {"verify", "hang_up", "report", "trust"}


def apply_action(state: RoundState, action: str) -> str:
    """Handle verify, hang_up, report or trust. Always ends the round; returns the ending code."""
    _require_active(state)
    if action not in ENDING_ACTIONS:
        raise ValueError(f"not an ending action: {action}")
    clean = state.mistakes == 0 and not state.info_shared
    if action != "trust":
        _resolve_pending(state, fell_for_it=False)  # walking away resists the last tactic

    if action == "verify":
        state.verified = True
        state.score.append(ScoreEvent("Verified independently", POINTS_VERIFY))
        if state.is_scam:
            return _finish(state, "OUTSMARTED" if clean else "ESCAPED")
        return _finish(state, "LUCKY" if state.sensitive_shared else "SMART_AND_SAFE")

    if action == "trust":
        if state.is_scam:
            _resolve_pending(state, fell_for_it=True)
            return _finish(state, "SCAMMED")
        return _finish(state, _legit_trust_ending(state))

    # hang_up or report
    if not state.is_scam:
        state.score.append(ScoreEvent("False alarm on a real contact", POINTS_FALSE_ALARM))
        return _finish(state, "FALSE_ALARM")
    if action == "report":
        state.score.append(ScoreEvent("Correctly reported the scam", POINTS_CORRECT_REPORT))
        return _finish(state, "OUTSMARTED" if clean else "ESCAPED")
    # Hanging up is safe, but the best ending needs the player to show they knew why.
    return _finish(state, "OUTSMARTED" if clean and state.recognized else "ESCAPED")


def open_link(state: RoundState, link: str) -> None:
    """The player tapped a link in the chat. Raises risk; does not use a turn."""
    _require_active(state)
    state.links_opened.append(link)
    state.risk = _clamp(state.risk + LINK_RISK)
    if state.is_scam:
        if "suspicious_link" not in state.tactics_used:
            state.tactics_used.append("suspicious_link")
        state.mistakes += 1


# ---------------------------------------------------------------------------
# Scoring and progression
# ---------------------------------------------------------------------------

def xp_for_round(state: RoundState) -> int:
    """XP is the round's points plus a completion bonus (none if scammed)."""
    bonus = 0 if state.ending == "SCAMMED" else COMPLETION_BONUS_XP
    return state.points + bonus


def xp_threshold(level: int) -> int:
    """Total XP needed to reach a level: 0, 100, 300, 600, 1000, ..."""
    return 50 * level * (level - 1)


def level_for_xp(xp: int) -> int:
    level = 1
    while xp >= xp_threshold(level + 1):
        level += 1
    return level


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


def _require_active(state: RoundState) -> None:
    if state.ended:
        raise RoundEndedError("round already ended")


class RoundEndedError(Exception):
    pass


def _last_pending_request(state: RoundState) -> str | None:
    for event in reversed(state.timeline):
        if event.response != "no_response":
            break
        if event.flag_id in REQUEST_TACTICS:
            return event.flag_id
    return None


def _resolve_pending(state: RoundState, fell_for_it: bool) -> None:
    """Mark the tactics the player just answered as resisted or fell_for_it."""
    for event in state.timeline:
        if event.response == "no_response" and event.flag_id in RED_FLAGS:
            event.response = "fell_for_it" if fell_for_it else "resisted"


def _legit_trust_ending(state: RoundState) -> str:
    if state.noticed and not state.sensitive_shared:
        return "SMART_AND_SAFE"
    return "LUCKY"


def _turn_limit_ending(state: RoundState) -> str:
    if state.is_scam:
        return "ALMOST_SCAMMED"
    return _legit_trust_ending(state)


def _finish(state: RoundState, ending: str) -> str:
    state.ending = ending
    for event in state.timeline:
        if event.flag_id in GREEN_FLAGS:
            event.response = "noticed" if event.flag_id in state.noticed else "missed"
    if ending in PAR_BONUS_ENDINGS and state.turns < state.par_turns:
        under = state.par_turns - state.turns
        state.score.append(ScoreEvent(f"Finished {under} turn(s) under par",
                                      under * POINTS_PER_TURN_UNDER_PAR))
    return ending


def flag_dict(flag_id: str | None) -> dict | None:
    """A flag id as the full object the API returns."""
    f = ALL_FLAGS.get(flag_id or "")
    if not f:
        return None
    return {"id": f.id, "kind": f.kind, "label": f.label, "explanation": f.explanation}
