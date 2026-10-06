"""Train Your Weakness: a focus makes the scammer lead with the player's weakest tactics."""

import random

import pytest
from fastapi.testclient import TestClient

from app import engine, game, store
from app.ai import prompts
from app.ai.base import TurnContext
from app.main import app
from app.scenarios import get_scenario, new_id_card

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_store():
    store.clear()


def new_player() -> str:
    return client.post("/api/player", json={}).json()["player_id"]


def start(pid: str, focus: str | None, scenario: str = "bank_alert"):
    return client.post("/api/round/start", json={"player_id": pid, "scenario_id": scenario, "focus": focus})


def test_unknown_focus_is_rejected():
    r = start(new_player(), "mind_control")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_focus_makes_the_scammer_lead_with_those_tactics(monkeypatch):
    monkeypatch.setattr(engine, "assign_is_scam", lambda *a, **k: True)
    rnd = start(new_player(), "urgency").json()
    assert rnd["focus"] == {"category": "urgency", "label": "Urgency & fear"}
    state = store.get_round(rnd["round_id"]).state
    assert set(state.focus_tactics) == {"urgency", "fear"}  # the bank scam's tactics in that category

    client.post(f"/api/round/{rnd['round_id']}/message", json={"text": "hmm tell me more"})
    assert state.tactics_used[1] in {"urgency", "fear"}  # first reply after the opening


def test_legit_training_round_has_no_focus_tactics(monkeypatch):
    monkeypatch.setattr(engine, "assign_is_scam", lambda *a, **k: False)
    rnd = start(new_player(), "urgency").json()
    assert store.get_round(rnd["round_id"]).state.focus_tactics == []


@pytest.mark.parametrize("focus,ratio", [
    (None, 0.65),
    ("urgency", game.FOCUS_SCAM_RATIO),
    ("real_contacts", game.FOCUS_REAL_CONTACTS_SCAM_RATIO),
])
def test_focus_changes_the_scam_legit_odds_but_never_guarantees(monkeypatch, focus, ratio):
    seen = {}
    def capture(history, rng, scam_ratio):
        seen["ratio"] = scam_ratio
        return True
    monkeypatch.setattr(engine, "assign_is_scam", capture)
    start(new_player(), focus)
    assert seen["ratio"] == ratio
    assert 0 < seen["ratio"] < 1


def test_prompt_names_the_focus_tactics():
    scenario = get_scenario("bank_alert")
    state = engine.RoundState(is_scam=True, id_card=new_id_card(scenario, random.Random(1)), objective="x",
                              focus_tactics=["urgency", "fear"])
    text = prompts.character_system(TurnContext(scenario=scenario, state=state))
    assert "Training focus" in text and "urgency" in text
    state.focus_tactics = []
    assert "Training focus" not in prompts.character_system(TurnContext(scenario=scenario, state=state))


def test_full_loop_weakness_card_then_training_round(monkeypatch):
    """Fall for urgency, see it on the Train Your Weakness card, start a round focused on it."""
    monkeypatch.setattr(engine, "assign_is_scam", lambda *a, **k: True)
    pid = new_player()
    rid = start(pid, None).json()["round_id"]
    client.post(f"/api/round/{rid}/message", json={"text": "ok sure"})        # goes along: falls for it
    client.post(f"/api/round/{rid}/action", json={"action": "hang_up"})
    pick = client.get(f"/api/scenarios?player_id={pid}").json()["train_your_weakness"]
    assert pick and pick["percent"] < 100

    rnd = start(pid, pick["category"], pick["scenario_id"]).json()
    assert rnd["focus"]["category"] == pick["category"]
