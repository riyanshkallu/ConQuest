"""Scenario Generator: per-round names and numbers, the safety checks, and the fallback."""

import asyncio
import json
import random
import re
from types import SimpleNamespace

import pytest

from app import game, progress, store
from app.ai.generator import check_vars
from app.ai.live import LiveAI
from app.config import Settings
from app.scenarios import get_scenario, make_variant

BANK = get_scenario("bank_alert")
JOB = get_scenario("job_offer")
FAMILY = get_scenario("family_emergency")

GOOD = {
    "bank_alert": {"bank": "Maple Valley Credit Union", "bank_short": "Maple Valley", "merchant": "Gadget Harbor"},
    "job_offer": {"company": "Cedar Ridge Supply", "recruiter": "Priya Okonkwo"},
    "family_emergency": {"relative": "Rowan", "aunt_name": "Marisol", "pet": "Pickles", "gift_store": "GameNest"},
}


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        content = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class NamesAI:
    """A stand-in AI whose only job is to invent names."""

    def __init__(self, names):
        self.names = names

    async def scenario_vars(self, scenario):
        return self.names.get(scenario.id)


# --- Per-round variants -----------------------------------------------------------

def test_variant_uses_generated_names_and_derives_links():
    v = make_variant(BANK, random.Random(1), GOOD["bank_alert"]).raw["vars"]
    assert v["bank"] == "Maple Valley Credit Union"
    assert v["link"] == "maplevalley-secure-verify.example/login"

    v = make_variant(JOB, random.Random(1), GOOD["job_offer"]).raw["vars"]
    assert v["recruiter_first"] == "Priya"
    assert v["careers_link"] == "careers.cedarridgesupply.example"
    assert v["handle"] == "@priya.cedarridgesupply"

    v = make_variant(FAMILY, random.Random(1), GOOD["family_emergency"]).raw["vars"]
    assert v["parent"] == "Aunt Marisol"


def test_numbers_change_every_round_even_without_ai():
    amounts = {make_variant(BANK, random.Random(seed)).raw["vars"]["amount"] for seed in range(20)}
    assert len(amounts) > 15
    for seed in range(20):
        v = make_variant(BANK, random.Random(seed)).raw["vars"]
        assert re.fullmatch(r"\$\d{2,3}\.\d\d", v["amount"]) and len(v["short_code"]) == 5


def test_family_phone_numbers_are_fictional_and_different():
    for seed in range(50):
        v = make_variant(FAMILY, random.Random(seed)).raw["vars"]
        assert v["parent_phone"] != v["friend_phone"]
        assert re.fullmatch(r"\(614\) 555-01\d\d", v["parent_phone"])


def test_seed_is_not_changed_by_variants():
    make_variant(BANK, random.Random(1), GOOD["bank_alert"])
    assert get_scenario("bank_alert").raw["vars"]["bank"] == "Buckeye Federal Credit Union"


# --- Safety checks on AI-invented names -------------------------------------------

@pytest.mark.parametrize("scenario", [BANK, JOB, FAMILY], ids=lambda s: s.id)
def test_good_names_pass(scenario):
    assert check_vars(GOOD[scenario.id], scenario) is None


@pytest.mark.parametrize("change,problem", [
    ({"bank": "Huntington Community Bank", "bank_short": "Huntington"}, "real name"),
    ({"merchant": "Best Buy Outlet"}, "real name"),
    ({"merchant": "Gadgets4U"}, "digits"),
    ({"merchant": "gadgetharbor.com"}, "web address"),
    ({"merchant": "A" * 41}, "too long"),
    ({"bank_short": "Oak Hill"}, "isn't part of bank"),
])
def test_bad_bank_names_are_rejected(change, problem):
    assert problem in check_vars({**GOOD["bank_alert"], **change}, BANK)


def test_missing_or_extra_keys_are_rejected():
    assert "wrong keys" in check_vars({"bank": "Maple Valley Credit Union"}, BANK)
    assert "wrong keys" in check_vars({**GOOD["bank_alert"], "extra": "x"}, BANK)


def test_people_cannot_share_the_players_name_or_each_others():
    assert "clash" in check_vars({**GOOD["job_offer"], "recruiter": "Jordan Smith"}, JOB)
    assert "share a name" in check_vars({**GOOD["family_emergency"], "aunt_name": "Rowan"}, FAMILY)


# --- Live generator with a fake model ---------------------------------------------

def live_ai(replies) -> LiveAI:
    ai = LiveAI(Settings(_env_file=None))
    ai.llm.clients = {"groq": FakeClient(replies)}
    ai.generator_models = [("groq", "m")]
    return ai


def test_live_generator_returns_checked_names():
    ai = live_ai([json.dumps(GOOD["bank_alert"])])
    assert asyncio.run(ai.scenario_vars(BANK)) == GOOD["bank_alert"]


def test_live_generator_falls_back_when_names_are_unsafe():
    bad = json.dumps({**GOOD["bank_alert"], "bank": "Chase Bank", "bank_short": "Chase"})
    ai = live_ai([bad, bad])  # bad twice: regenerated once, then give up
    assert asyncio.run(ai.scenario_vars(BANK)) is None


# --- A whole round with generated names -------------------------------------------

@pytest.mark.parametrize("scenario_id", ["bank_alert", "job_offer", "family_emergency"])
def test_round_uses_generated_names_everywhere(scenario_id):
    store.clear()
    player = progress.Player(id="p_test")
    store.save_player(player)
    names = GOOD[scenario_id]
    start = asyncio.run(game.start_round(player, scenario_id, NamesAI(GOOD)))
    rnd = store.get_round(start.round_id)
    end = asyncio.run(game.do_action(rnd, "verify", None, NamesAI(GOOD)))
    text = json.dumps([start.model_dump(), end.model_dump(), game.get_result(rnd).model_dump()])

    main_name = next(iter(names.values()))
    assert main_name in text
    seed_names = {"bank_alert": "Buckeye Federal", "job_offer": "Riverside", "family_emergency": "Biscuit"}
    assert seed_names[scenario_id] not in text  # the hand-written name was fully replaced
    assert not re.search(r"\{[a-z_]+\}", text), "unfilled placeholder"
    if scenario_id == "bank_alert":
        assert start.id_card.bank == "Maple Valley Credit Union"
        assert end.verification_call.official_name == "Maple Valley"
    if scenario_id == "family_emergency":
        assert start.id_card.family.memory_answer == "Pickles"
        assert end.verification_call.official_name == "Aunt Marisol"


def test_wrapped_generator_reply_is_unwrapped():
    wrapped = json.dumps({"invent_these": GOOD["bank_alert"], "examples_to_avoid": "x", "style_hint": "y"})
    ai = live_ai([wrapped])
    assert asyncio.run(ai.scenario_vars(BANK)) == GOOD["bank_alert"]


def test_generator_request_is_plain_text_with_a_letter_hint_per_name():
    from app.ai.generator import generator_user
    text = generator_user(FAMILY, random.Random(3))
    assert not text.lstrip().startswith("{")
    assert text.count("start it with the letter") == 4
    assert '"relative": "..."' in text
    # bank_short must come from bank, so it gets no letter hint
    assert generator_user(BANK, random.Random(3)).count("start it with the letter") == 2
