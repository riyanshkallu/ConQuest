"""Checks every scenario file in data/scenarios/, so a typo in a new scenario fails here
instead of in the middle of someone's round."""

import random
import re

import pytest

from app import engine
from app.ai.base import TurnContext
from app.ai.live import CharacterOut, check_character
from app.flags import GREEN_FLAGS, RED_FLAGS
from app.scenarios import load_scenarios, new_id_card, render

SCENARIOS = list(load_scenarios().values())
UNFILLED = re.compile(r"\{[a-z_0-9]+\}")


def make_ctx(scenario, is_scam: bool) -> TurnContext:
    card = new_id_card(scenario, random.Random(5))
    state = engine.RoundState(is_scam=is_scam, id_card=card, objective="x")
    # After any one-time code has arrived, when every line (even asking for the code) may be used
    return TurnContext(scenario=scenario, state=state, code_arrived=True)


def all_texts(value):
    """Every string inside a scenario file, however deeply nested."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from all_texts(v)
    elif isinstance(value, list):
        for v in value:
            yield from all_texts(v)


def test_the_three_planned_scenarios_exist():
    assert {s.id for s in SCENARIOS} >= {"bank_alert", "job_offer", "family_emergency"}


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_flags_and_orders_are_valid(scenario):
    scam, legit = scenario.version(True), scenario.version(False)
    assert set(scam["allowed_tactics"]) <= set(RED_FLAGS)
    assert set(legit["allowed_flags"]) <= set(GREEN_FLAGS)
    assert set(scam["lines"]) == set(scam["allowed_tactics"]), "every tactic needs fallback lines"
    assert set(legit["lines"]) == set(legit["allowed_flags"]), "every green flag needs fallback lines"
    assert scam["opening"]["flag"] in scam["allowed_tactics"]
    assert legit["opening"]["flag"] in legit["allowed_flags"]
    for key in ("tactic_order", "pushback_order"):
        assert set(scam.get(key, [])) <= set(scam["allowed_tactics"])
    for key in ("flag_order", "pushback_order"):
        assert set(legit.get(key, [])) <= set(legit["allowed_flags"])


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_verification_calls_are_complete(scenario):
    assert scenario.raw["verification_call_title"] and scenario.raw["verification_official"]
    for is_scam in (True, False):
        lines = scenario.version(is_scam)["verification_call"]
        assert {line["speaker"] for line in lines} <= {"official", "player"}
        assert lines[0]["speaker"] == "official"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_every_placeholder_is_filled(scenario):
    card = new_id_card(scenario, random.Random(1))
    for text in all_texts(scenario.raw):
        assert not UNFILLED.search(render(text, scenario, card)), text


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
@pytest.mark.parametrize("is_scam", [True, False], ids=["scam", "legit"])
def test_prewritten_lines_follow_the_same_rules_as_the_ai(scenario, is_scam):
    ctx = make_ctx(scenario, is_scam)
    version = scenario.version(is_scam)
    for flag, lines in version["lines"].items():
        for line in lines:
            text = render(line, scenario, ctx.state.id_card)
            out = CharacterOut(message=text, tactic=flag if is_scam else None,
                               green_flag=None if is_scam else flag)
            assert check_character(out, ctx) is None, f"{flag}: {text}"
