"""Runs the game: connects the engine, the AI roles, scenarios and storage.

Order of a player turn (from the plan):
  1. real-data blocker  2. trap item check  3. Player Analyzer  4. engine update
  5. ending check       6. AI Character reply (+ one-time code notification)

Never put is_scam, tactics, flags or pressure in a response before the round ends.
"""

from __future__ import annotations

import random
import re
from datetime import date

from . import engine, progress, schemas, store
from .ai.base import AIProvider, TurnContext
from .config import get_settings
from .explain import build_result, ending_out, explain_request
from .flags import RED_FLAGS
from .scenarios import Scenario, get_scenario, load_scenarios, make_variant, new_id_card, render

_rng = random.Random()
_LINK_RE = re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.example(?:/[\w./?=&%-]*)?", re.IGNORECASE)


class GameError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---------------------------------------------------------------------------
# Players and scenarios
# ---------------------------------------------------------------------------

def create_player(display_name: str | None) -> progress.Player:
    player = progress.Player(id=store.new_id("p"), display_name=display_name)
    store.save_player(player)
    return player


def require_player(player_id: str) -> progress.Player:
    player = store.get_player(player_id)
    if not player:
        raise GameError(404, "player_not_found", "No player with that id.")
    return player


def require_round(round_id: str) -> store.Round:
    rnd = store.get_round(round_id)
    if not rnd:
        raise GameError(404, "round_not_found", "No round with that id.")
    return rnd


def list_scenarios(player: progress.Player) -> schemas.ScenarioListResponse:
    scenarios = list(load_scenarios().values())
    cards = [schemas.ScenarioCard(id=s.id, title=s.title, channel=s.channel, difficulty=s.difficulty)
             for s in scenarios]
    weak = progress.weakest_category(player)
    pick = None
    if weak:
        scenario = _scenario_for_category(scenarios, weak["category"])
        pick = schemas.WeaknessPick(scenario_id=scenario.id, category=weak["category"],
                                    label=weak["label"], percent=weak["percent"])
    return schemas.ScenarioListResponse(scenarios=cards, train_your_weakness=pick)


def _scenario_for_category(scenarios: list[Scenario], category: str) -> Scenario:
    """A scenario whose scam version uses a tactic from the weak category."""
    matches = [s for s in scenarios
               if any(RED_FLAGS[t].category == category for t in s.version(True)["allowed_tactics"])]
    return _rng.choice(matches or scenarios)


def radar(player: progress.Player) -> schemas.RadarResponse:
    return schemas.RadarResponse(
        player_id=player.id, display_name=player.display_name, level=player.level, xp=player.xp,
        xp_for_next_level=engine.xp_threshold(player.level + 1), streak_days=player.streak_days,
        radar=progress.radar_rows(player), badges=progress.badge_list(player),
    )


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------

async def start_round(player: progress.Player, scenario_id: str, ai: AIProvider) -> schemas.StartRoundResponse:
    seed = get_scenario(scenario_id)
    if not seed:
        raise GameError(404, "scenario_not_found", "No scenario with that id.")
    # This round's own names and numbers (Scenario Generator). Falls back to the seed's names.
    scenario = make_variant(seed, _rng, await ai.scenario_vars(seed))
    settings = get_settings()
    is_scam = engine.assign_is_scam(player.history, _rng, settings.scam_ratio)
    version = scenario.version(is_scam)
    card = new_id_card(scenario, _rng)
    state = engine.RoundState(
        is_scam=is_scam, id_card=card, objective=version["objective"],
        objective_is_payment=version.get("objective_is_payment", False),
        max_turns=settings.max_turns, par_turns=scenario.raw.get("par_turns", 6),
    )
    rnd = store.Round(id=store.new_id("r"), player_id=player.id, scenario=scenario, state=state)

    opening = version["opening"]
    engine.record_character_move(state, opening.get("flag"))
    opening_msg = _add_contact_message(rnd, render(opening["text"], scenario, card), opening.get("flag"))
    store.save_round(rnd)

    return schemas.StartRoundResponse(
        round_id=rnd.id, scenario_id=scenario.id, channel=scenario.channel,
        difficulty=scenario.difficulty, max_turns=state.max_turns,
        contact=schemas.Contact(name=render(version["contact"]["name"], scenario, card),
                                handle=render(version["contact"]["handle"], scenario, card)),
        id_card=_id_card_out(card, scenario),
        opening_message=opening_msg,
        suggested_replies=_suggestions(rnd, "opening"),
    )


async def send_message(rnd: store.Round, text: str, ai: AIProvider) -> schemas.TurnResponse:
    state = rnd.state
    _require_active(rnd)

    reason = engine.blocked_reason(text, state.id_card)
    if reason:  # never recorded, never sent to the AI
        return schemas.TurnResponse(blocked=True, blocked_reason=reason,
                                    turn=state.turns, max_turns=state.max_turns)

    pre = engine.begin_turn(state, text)
    entry = _add_player_message(rnd, text)
    if state.ended:  # typed a trap item in a scam round
        entry.update(note=f"You gave away your {pre.traps[0]}.", mistake=True)
        return _ended_response(rnd, schemas.TurnResponse)

    ctx = _context(rnd, text)
    analysis = await ai.analyze(ctx)
    ending = engine.apply_analysis(state, analysis, pre)
    _annotate(entry, analysis, pre, state)
    if ending:
        return _ended_response(rnd, schemas.TurnResponse)
    return await _character_turn(rnd, ai, analysis.decision_type, schemas.TurnResponse)


async def do_action(rnd: store.Round, action: str, link: str | None, ai: AIProvider) -> schemas.ActionResponse:
    state = rnd.state
    _require_active(rnd)
    version = rnd.scenario.version(state.is_scam)

    if action == "open_link":
        sent_links = {l for m in rnd.transcript if m["sender"] == "contact" for l in m["links"]}
        if link not in sent_links:
            raise GameError(400, "invalid_request", "That link isn't in this conversation.")
        engine.open_link(state, link)
        return schemas.ActionResponse(turn=state.turns, max_turns=state.max_turns, hint=_hint(rnd))

    if action == "ask_proof":
        contact = render(version["contact"]["name"], rnd.scenario, state.id_card)
        text = f"How do I know this is really {contact}?"
        pre = engine.begin_turn(state, text)
        entry = _add_player_message(rnd, text)
        analysis = engine.ask_proof_analysis()
        ending = engine.apply_analysis(state, analysis, pre)
        _annotate(entry, analysis, pre, state)
        player_msg = schemas.Message(sender="player", text=text)
        if ending:
            resp = _ended_response(rnd, schemas.ActionResponse)
        else:
            resp = await _character_turn(rnd, ai, "challenge", schemas.ActionResponse)
        resp.player_message = player_msg
        return resp

    # verify, hang_up, report, trust: always end the round
    engine.apply_action(state, action)
    _add_notification(rnd, _ACTION_TEXT[action])
    resp = _ended_response(rnd, schemas.ActionResponse)
    if action == "verify":
        lines = [schemas.CallLine(speaker=l["speaker"], text=render(l["text"], rnd.scenario, state.id_card))
                 for l in version["verification_call"]]
        raw = rnd.scenario.raw
        resp.verification_call = schemas.VerificationCall(
            title=render(raw["verification_call_title"], rnd.scenario, state.id_card),
            official_name=render(raw["verification_official"], rnd.scenario, state.id_card),
            lines=lines)
    return resp


async def get_result(rnd: store.Round, ai: AIProvider) -> schemas.ResultResponse:
    if not rnd.state.ended:
        raise GameError(409, "round_not_ended", "The round hasn't ended yet.")
    if rnd.result is None:
        async with rnd.lock:  # two quick requests still run the Explainer only once
            if rnd.result is None:
                words = await ai.explain(explain_request(rnd))
                rnd.result = build_result(rnd, words)
    return rnd.result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_ACTION_TEXT = {
    "verify": "You called the organization using a number you already trust.",
    "hang_up": "You ended the conversation.",
    "report": "You reported this contact as a scam.",
    "trust": "You decided this contact was real.",
}


def _require_active(rnd: store.Round) -> None:
    if rnd.state.ended:
        raise GameError(409, "round_ended", "This round has already ended.")


async def _character_turn(rnd: store.Round, ai: AIProvider, decision: str, cls):
    state = rnd.state
    code_turn = rnd.scenario.raw.get("code_turn")
    code_now = not rnd.code_sent and code_turn is not None and state.turns >= code_turn

    ctx = _context(rnd, "", decision, code_now)
    move = await ai.character_move(ctx)
    engine.record_character_move(state, move.flag, move.pressure)
    reply = _add_contact_message(rnd, move.message, move.flag)

    notifications = []
    stage = "default"
    if code_now:
        rnd.code_sent = True
        stage = "after_code"
        text = render(rnd.scenario.raw["code_notification"], rnd.scenario, state.id_card)
        notifications.append(_add_notification(rnd, text))

    return cls(turn=state.turns, max_turns=state.max_turns, reply=reply, notifications=notifications,
               suggested_replies=_suggestions(rnd, stage), hint=_hint(rnd))


def _ended_response(rnd: store.Round, cls):
    _finalize(rnd)
    return cls(turn=rnd.state.turns, max_turns=rnd.state.max_turns, ended=True,
               ending=ending_out(rnd.state))


def _finalize(rnd: store.Round) -> None:
    """Apply the finished round to the player's progress, exactly once."""
    if rnd.finalized:
        return
    rnd.finalized = True
    player = store.get_player(rnd.player_id)
    rnd.xp_earned = engine.xp_for_round(rnd.state)
    if player:
        rnd.new_badges = progress.update_after_round(player, rnd.state, date.today())


def _context(rnd: store.Round, text: str, decision: str = "neutral", code_now: bool = False) -> TurnContext:
    return TurnContext(
        scenario=rnd.scenario, state=rnd.state,
        transcript=[{"sender": m["sender"], "text": m["text"]} for m in rnd.transcript],
        player_text=text, last_decision=decision, code_just_sent=code_now,
    )


def _add_contact_message(rnd: store.Round, text: str, flag: str | None) -> schemas.Message:
    links = _LINK_RE.findall(text)
    rnd.transcript.append({"turn": rnd.state.turns, "sender": "contact", "text": text,
                           "links": links, "flag": flag})
    return schemas.Message(sender="contact", text=text, links=links)


def _add_player_message(rnd: store.Round, text: str) -> dict:
    entry = {"turn": rnd.state.turns, "sender": "player", "text": text, "links": []}
    rnd.transcript.append(entry)
    return entry


def _add_notification(rnd: store.Round, text: str) -> schemas.Message:
    rnd.transcript.append({"turn": rnd.state.turns, "sender": "notification", "text": text, "links": []})
    return schemas.Message(sender="notification", text=text)


def _annotate(entry: dict, analysis: engine.Analysis, pre: engine.PreCheck, state: engine.RoundState) -> None:
    """The note shown when the player taps their own message in the flagged transcript."""
    if pre.traps:
        entry.update(note=f"You shared your {pre.traps[0]}. A real contact never needs it.", mistake=True)
    elif pre.minor:
        entry.update(note=f"You shared your {pre.minor[0]}.", mistake=True)
    else:
        good = analysis.decision_type in ("challenge", "safe_verification")
        bad = analysis.mistake or (state.is_scam and analysis.decision_type.endswith("compliance"))
        entry.update(note=analysis.reason or None, good=good, mistake=bad)


def _suggestions(rnd: store.Round, stage: str) -> list[str]:
    options = rnd.scenario.raw.get("suggested_replies", {})
    replies = options.get(stage) or options.get("default", [])
    return [render(r, rnd.scenario, rnd.state.id_card) for r in replies]


def _hint(rnd: store.Round) -> schemas.Hint | None:
    player = store.get_player(rnd.player_id)
    return schemas.Hint(suspicion=rnd.state.suspicion) if player and player.hints else None


def _id_card_out(card: engine.IdCard, scenario: Scenario) -> schemas.IdCardOut:
    vars_ = scenario.raw.get("vars", {})
    gift = gaming = None
    if card.gift_card_code:
        gift = schemas.GiftCard(store=vars_.get("gift_store", "PlayMart"),
                                amount=vars_.get("gift_amount", 200), code=card.gift_card_code)
    if card.gaming_username:
        gaming = schemas.GamingAccount(game=vars_.get("game", "Blockcraft"), username=card.gaming_username)
    family = None
    if "id_card_family" in scenario.raw:
        family = schemas.FamilyInfo(**{k: render(v, scenario, card)
                                       for k, v in scenario.raw["id_card_family"].items()})
    return schemas.IdCardOut(name=card.name, email=card.email, phone=card.phone, bank=card.bank,
                             card_number=card.card_number, card_last4=card.card_last4,
                             password=card.password, gift_card=gift, gaming_account=gaming,
                             family=family)
