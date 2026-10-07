"""Player progress: XP, level, daily streak, Scam Radar and badges.

Pure logic like the engine. Storage (memory now, Supabase later) lives in store.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from . import engine
from .flags import RADAR_CATEGORIES, RED_FLAGS

GOOD_CALL_ENDINGS = {"OUTSMARTED", "ESCAPED", "SMART_AND_SAFE"}

BADGES: dict[str, tuple[str, str]] = {
    "first_escape": ("First Escape", "Finish a scam round without getting scammed."),
    "no_mistakes": ("No Mistakes", "Get the best ending in a round without a single mistake."),
    "detective": ("Detective", "Make five correct scam-or-legit calls in a row."),
    "verifier": ("Verifier", "Verify independently ten times."),
    # Needs the frontend to tell us about other profiles on the device (see api.md).
    "family_player": ("Family Player", "Add a second player on the same device."),
}


@dataclass
class Player:
    id: str
    display_name: str | None = None
    hints: bool = False
    save_conversations: bool = True
    xp: int = 0
    streak_days: int = 0
    last_played: date | None = None
    history: list[bool] = field(default_factory=list)  # is_scam of every finished round
    radar: dict[str, list[int]] = field(
        default_factory=lambda: {c: [0, 0] for c in RADAR_CATEGORIES})  # [encountered, resisted]
    badges: list[str] = field(default_factory=list)
    verify_count: int = 0
    good_call_streak: int = 0

    @property
    def level(self) -> int:
        return engine.level_for_xp(self.xp)

    def reset(self) -> None:
        fresh = Player(self.id, self.display_name, self.hints, self.save_conversations)
        self.__dict__.update(fresh.__dict__)


def update_after_round(player: Player, state: engine.RoundState, today: date) -> list[str]:
    """Apply a finished round to the player's progress. Returns newly earned badge ids."""
    player.history.append(state.is_scam)
    player.xp += engine.xp_for_round(state)
    _update_streak(player, today)

    if state.is_scam:
        for event in state.timeline:
            if event.flag_id in RED_FLAGS:
                row = player.radar[RED_FLAGS[event.flag_id].category]
                row[0] += 1
                row[1] += event.response == "resisted"
    else:
        row = player.radar["real_contacts"]
        row[0] += 1
        row[1] += state.ending == "SMART_AND_SAFE"

    player.verify_count += state.verified
    player.good_call_streak = player.good_call_streak + 1 if state.ending in GOOD_CALL_ENDINGS else 0

    earned = []
    checks = {
        "first_escape": state.ending in ("OUTSMARTED", "ESCAPED"),
        "no_mistakes": state.ending in ("OUTSMARTED", "SMART_AND_SAFE") and state.mistakes == 0,
        "detective": player.good_call_streak >= 5,
        "verifier": player.verify_count >= 10,
    }
    for badge, ok in checks.items():
        if ok and badge not in player.badges:
            player.badges.append(badge)
            earned.append(badge)
    return earned


def _update_streak(player: Player, today: date) -> None:
    if player.last_played == today:
        return
    if player.last_played == today - timedelta(days=1):
        player.streak_days += 1
    else:
        player.streak_days = 1
    player.last_played = today


def radar_rows(player: Player) -> list[dict]:
    rows = []
    for category, label in RADAR_CATEGORIES.items():
        encountered, resisted = player.radar[category]
        percent = round(100 * resisted / encountered) if encountered else None
        rows.append({"category": category, "label": label, "encountered": encountered,
                     "resisted": resisted, "percent": percent})
    return rows


def weakness_score(encountered: int, resisted: int) -> float:
    """How well the player handles a category, allowing for how little data there may be.

    Adds one imaginary win and one imaginary loss (a Beta(1,1) prior, the plan's Bayesian idea),
    so "resisted 1 of 1" scores 0.67 rather than a perfect 1.0, and the score settles on the
    real rate as rounds add up.
    """
    return (resisted + 1) / (encountered + 2)


def weakest_category(player: Player) -> dict | None:
    """The radar row the player is weakest at, for the Train Your Weakness card.

    Ranked by weakness_score; on a tie, the category seen more often (more evidence) wins.
    The row keeps its real percent for display.
    """
    rows = [r for r in radar_rows(player) if r["encountered"]]
    if not rows:
        return None
    return min(rows, key=lambda r: (weakness_score(r["encountered"], r["resisted"]), -r["encountered"]))


def badge_list(player: Player) -> list[dict]:
    return [{"id": b, "name": name, "description": desc, "earned": b in player.badges}
            for b, (name, desc) in BADGES.items()]
