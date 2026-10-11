"""Coaching tips: only with hints on, based only on what the player did, identical in scam and legit rounds."""

import pytest
from fastapi.testclient import TestClient

from app import engine, game, store
from app.main import app

client = TestClient(app)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    store.clear()
    clock = Clock()
    monkeypatch.setattr(game, "_now", clock)
    return clock


def start(monkeypatch, is_scam: bool, hints: bool = True) -> dict:
    monkeypatch.setattr(engine, "assign_is_scam", lambda *a, **k: is_scam)
    pid = client.post("/api/player", json={}).json()["player_id"]
    client.patch(f"/api/player/{pid}/settings", json={"hints": hints})
    return client.post("/api/round/start", json={"player_id": pid, "scenario_id": "bank_alert"}).json()


def say(rnd: dict, text: str, clock: Clock, after: float) -> dict:
    clock.now += after
    return client.post(f"/api/round/{rnd['round_id']}/message", json={"text": text}).json()


both = pytest.mark.parametrize("is_scam", [True, False], ids=["scam", "legit"])


@both
def test_no_tips_with_hints_off(monkeypatch, setup, is_scam):
    rnd = start(monkeypatch, is_scam, hints=False)
    assert say(rnd, "ok sure", setup, after=1)["coach_tip"] is None


@both
def test_going_along_fast_gets_the_slow_down_tip(monkeypatch, setup, is_scam):
    rnd = start(monkeypatch, is_scam)
    tip = say(rnd, "ok sure", setup, after=2)["coach_tip"]
    assert tip == "You answered in 2 seconds. Scammers count on quick replies, so it's OK to pause and check."


@both
def test_going_along_slowly_on_an_early_turn_gets_the_ask_first_tip(monkeypatch, setup, is_scam):
    rnd = start(monkeypatch, is_scam)
    assert say(rnd, "ok sure", setup, after=20)["coach_tip"] == game.COACH_TIPS["ask_first"]


@both
def test_sharing_a_personal_detail_gets_the_personal_tip(monkeypatch, setup, is_scam):
    rnd = start(monkeypatch, is_scam)
    email = rnd["id_card"]["email"]
    assert say(rnd, f"my email is {email}", setup, after=20)["coach_tip"] == game.COACH_TIPS["personal"]


@both
def test_no_tip_after_pushing_back(monkeypatch, setup, is_scam):
    rnd = start(monkeypatch, is_scam)
    assert say(rnd, "who is this?", setup, after=20)["coach_tip"] is None
    assert say(rnd, "ok sure", setup, after=20)["coach_tip"] is None  # already asked who they are


@both
def test_each_tip_shows_once_per_round(monkeypatch, setup, is_scam):
    rnd = start(monkeypatch, is_scam)
    first = say(rnd, "ok sure", setup, after=1)["coach_tip"]
    second = say(rnd, "ok", setup, after=1)["coach_tip"]
    assert first.startswith("You answered in") and second == game.COACH_TIPS["ask_first"]
    assert say(rnd, "fine", setup, after=1)["coach_tip"] is None


@both
def test_tapping_a_link(monkeypatch, setup, is_scam):
    rnd = start(monkeypatch, is_scam)
    link = "example-link.example/login"
    store.get_round(rnd["round_id"]).transcript.append(
        {"turn": 0, "sender": "contact", "text": link, "links": [link], "flag": None})
    r = client.post(f"/api/round/{rnd['round_id']}/action", json={"action": "open_link", "link": link}).json()
    if is_scam:  # the scammer's fake site ends the round; the result screen explains it
        assert r["ended"] and r["ending"]["code"] == "SCAMMED"
        result = client.get(f"/api/round/{rnd['round_id']}/result").json()
        assert "You opened a link the scammer sent." in result["explanation"]["mistakes"]
    else:  # a real contact's link is safe, so the round goes on with a tip
        assert not r["ended"] and r["coach_tip"] == game.COACH_TIPS["link"]


def test_sharing_a_code_with_a_real_contact_gets_the_code_tip(monkeypatch, setup):
    rnd = start(monkeypatch, is_scam=False)
    card = rnd["id_card"]["card_number"]
    r = say(rnd, f"here is my card {card}", setup, after=20)
    assert not r["ended"] and r["coach_tip"] == game.COACH_TIPS["code"]
