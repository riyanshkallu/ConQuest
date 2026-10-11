"""Builds the end-of-round result: reveal, Scam Autopsy / Legit Breakdown, flagged transcript, tip.

Every fact here comes from the engine. The AI Explainer (ai/explainer.py) may supply
conversation-specific wording for the timeline cards and the contact's flagged messages;
whatever it doesn't supply uses the engine's own text below.
"""

from __future__ import annotations

from collections import Counter

from . import engine, schemas
from .ai.base import ExplainerText, ExplainRequest
from .flags import ALL_FLAGS, GREEN_FLAGS, RADAR_CATEGORIES, RED_FLAGS, TIPS
from .progress import BADGES
from .scenarios import render
from .store import Round

# Which flag is the most telling clue, when several showed up.
RED_CLUE_ORDER = ["credential_request", "unusual_payment", "financial_pressure", "suspicious_link",
                  "secrecy", "platform_switch", "fake_reward", "urgency", "fear",
                  "emotional_manipulation", "authority", "trust_building"]
GREEN_CLUE_ORDER = ["no_credentials_asked", "invites_verification", "checkable_details", "accepts_no",
                    "official_channels", "no_pressure", "no_secrecy", "normal_payment"]


def ending_out(state: engine.RoundState) -> schemas.Ending:
    title, _, is_scam = engine.ENDINGS[state.ending]
    return schemas.Ending(code=state.ending, title=title, message=engine.ending_message(state),
                          is_scam=is_scam)


def explain_request(rnd: Round) -> ExplainRequest:
    """The facts the Explainer may write about."""
    state = rnd.state
    version = rnd.scenario.version(state.is_scam)
    return ExplainRequest(
        is_scam=state.is_scam,
        ending_title=engine.ENDINGS[state.ending][0],
        contact_name=render(version["contact"]["name"], rnd.scenario, state.id_card),
        id_card=state.id_card,
        messages=[{"index": i, "sender": m["sender"], "text": m["text"], "flag": m.get("flag")}
                  for i, m in enumerate(rnd.transcript)],
        flags=[card.flag.id for card in _timeline(state)],
    )


def build_result(rnd: Round, words: ExplainerText | None = None) -> schemas.ResultResponse:
    state = rnd.state
    words = words or ExplainerText()
    weakness = _biggest_weakness(state)
    tip_category = weakness or _first_category(state)
    tip_id, tip_text = TIPS[tip_category]

    return schemas.ResultResponse(
        round_id=rnd.id,
        scenario_id=rnd.scenario.id,
        ending=ending_out(state),
        biggest_clue=_biggest_clue(state),
        points=state.points,
        points_breakdown=[schemas.PointsLine(label=e.label, points=e.points) for e in state.score],
        xp_earned=rnd.xp_earned,
        explanation=schemas.Explanation(
            type="scam_autopsy" if state.is_scam else "legit_breakdown",
            timeline=[card.model_copy(update={"summary": words.timeline.get(card.flag.id, card.summary)})
                      for card in _timeline(state)],
            good_decisions=_good_decisions(rnd),
            mistakes=_mistakes(rnd),
            best_decision=_best_decision(rnd),
            biggest_weakness=(schemas.Weakness(category=weakness, label=RADAR_CATEGORIES[weakness])
                              if weakness else None),
            scam_twin=_scam_twin(rnd) if state.ending == "LUCKY" else None,
        ),
        transcript=[
            schemas.TranscriptEntry(
                index=i, turn=m["turn"], sender=m["sender"], text=m["text"],
                flag=engine.flag_dict(m.get("flag")), note=words.messages.get(i, m.get("note")),
            )
            for i, m in enumerate(rnd.transcript)
        ],
        tip=schemas.Tip(id=tip_id, text=tip_text),
        new_badges=[schemas.Badge(id=b, name=BADGES[b][0], description=BADGES[b][1])
                    for b in rnd.new_badges],
    )


def _biggest_clue(state: engine.RoundState) -> str:
    if state.is_scam:
        for f in RED_CLUE_ORDER:
            if f in state.tactics_used:
                return RED_FLAGS[f].explanation
        return "They contacted you out of nowhere and pushed you to act."
    for f in GREEN_CLUE_ORDER:
        if f in state.green_flags_shown:
            return GREEN_FLAGS[f].explanation
    return "They never asked for anything a scammer would want."


def _timeline(state: engine.RoundState) -> list[schemas.TimelineCard]:
    """One card per flag, at the turn it first appeared."""
    cards: dict[str, schemas.TimelineCard] = {}
    for event in state.timeline:
        flag = ALL_FLAGS[event.flag_id]
        card = cards.get(event.flag_id)
        if card is None:
            cards[event.flag_id] = schemas.TimelineCard(
                turn=event.turn, flag=engine.flag_dict(event.flag_id),
                summary=flag.explanation, player_response=event.response)
        elif event.response == "fell_for_it" or card.player_response == "no_response":
            card.player_response = event.response  # falling for it once is what matters
    return list(cards.values())


def _biggest_weakness(state: engine.RoundState) -> str | None:
    if not state.is_scam:
        return "real_contacts" if state.ending in ("LUCKY", "FALSE_ALARM") else None
    fell = Counter(RED_FLAGS[e.flag_id].category for e in state.timeline
                   if e.flag_id in RED_FLAGS and e.response == "fell_for_it")
    return fell.most_common(1)[0][0] if fell else None


def _first_category(state: engine.RoundState) -> str:
    for f in state.tactics_used:
        return RED_FLAGS[f].category
    return "real_contacts"


def _good_decisions(rnd: Round) -> list[str]:
    good = [m["note"] for m in rnd.transcript
            if m["sender"] == "player" and m.get("good") and m.get("note")]
    good += [e.label for e in rnd.state.score if e.points > 0 and e.label.startswith(("Refused", "Spotted", "Noticed"))]
    return good


def _mistakes(rnd: Round) -> list[str]:
    bad = [e.label for e in rnd.state.score if e.points < 0]
    if rnd.state.links_opened:
        bad.append("You opened a link the scammer sent." if rnd.state.is_scam else
                   "You opened a link in a message you weren't expecting. It was safe this time, "
                   "but open the official app or website yourself instead.")
    bad += [m["note"] for m in rnd.transcript
            if m["sender"] == "player" and m.get("mistake") and m.get("note") and m["note"] not in bad]
    return bad


def _best_decision(rnd: Round) -> str | None:
    state = rnd.state
    if state.verified:
        return "You verified independently, using a number or app you already trust."
    if state.is_scam and state.ending in ("OUTSMARTED", "ESCAPED") and state.recognized:
        return f"You recognized their {RED_FLAGS[state.recognized[0]].label.lower()} tactic."
    good = _good_decisions(rnd)
    return good[0] if good else None


def _scam_twin(rnd: Round) -> schemas.ScamTwin | None:
    scam = rnd.scenario.version(True)
    if "key_message" not in scam:
        return None
    card = rnd.state.id_card
    return schemas.ScamTwin(contact_name=render(scam["contact"]["name"], rnd.scenario, card),
                            text=render(scam["key_message"], rnd.scenario, card))
