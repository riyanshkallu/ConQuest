"""Surprise me (random scenario) and demo mode (for recording the video)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db, store
from app.config import get_settings
from app.main import app
from scripts import playtest_report as report

client = TestClient(app)
KEY = "test-demo-key"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    store.clear()
    monkeypatch.setattr(get_settings(), "demo_key", KEY)


def new_player() -> str:
    return client.post("/api/player", json={}).json()["player_id"]


def start(pid: str, scenario: str = "bank_alert", **extra):
    return client.post("/api/round/start", json={"player_id": pid, "scenario_id": scenario, **extra})


# --- Surprise me -------------------------------------------------------------

def test_surprise_me_starts_a_real_scenario():
    r = start(new_player(), "random")
    assert r.status_code == 201 and r.json()["scenario_id"] in {
        "bank_alert", "family_emergency", "job_offer", "package_delivery", "tech_support"}


def test_surprise_me_never_repeats_the_last_scenario():
    pid = new_player()
    last = None
    for _ in range(25):
        rnd = start(pid, "random").json()
        assert rnd["scenario_id"] != last
        last = rnd["scenario_id"]
        client.post(f"/api/round/{rnd['round_id']}/action", json={"action": "report"})


def test_surprise_me_works_with_a_focus():
    rnd = start(new_player(), "random", focus="urgency").json()
    assert rnd["focus"]["category"] == "urgency"


# --- Demo mode ------------------------------------------------------------------

def demo(force: str, seed: int | None = 7, key: str = KEY) -> dict:
    return {"demo": {"key": key, "force": force, "seed": seed}}


@pytest.mark.parametrize("force,is_scam", [("scam", True), ("legit", False)])
def test_demo_forces_scam_or_legit(force, is_scam):
    for _ in range(5):
        rid = start(new_player(), **demo(force)).json()["round_id"]
        assert store.get_round(rid).state.is_scam is is_scam


def test_same_seed_gives_the_same_details_for_the_scam_and_legit_takes():
    scam = start(new_player(), **demo("scam", seed=7)).json()
    legit = start(new_player(), **demo("legit", seed=7)).json()
    assert scam["id_card"] == legit["id_card"]                 # same card, name, bank
    assert scam["contact"] == legit["contact"]
    amount = store.get_round(scam["round_id"]).scenario.raw["vars"]["amount"]
    assert amount in scam["opening_message"]["text"] and amount in legit["opening_message"]["text"]


def test_wrong_key_or_demo_off_is_refused(monkeypatch):
    r = start(new_player(), **demo("scam", key="nope"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    monkeypatch.setattr(get_settings(), "demo_key", "")
    assert start(new_player(), **demo("scam", key="")).status_code == 403


def test_demo_rounds_are_saved_but_left_out_of_the_report():
    rid = start(new_player(), **demo("scam")).json()["round_id"]
    client.post(f"/api/round/{rid}/action", json={"action": "report"})
    with db.get_engine().connect() as conn:
        details = conn.execute(select(db.rounds.c.details)).scalar()
    assert details["demo"] is True
    assert report.load_rounds(db.get_engine(), None, None) == []
