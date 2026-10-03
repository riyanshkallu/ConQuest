"""End-to-end API tests in mock mode: full rounds played over HTTP, like the frontend will."""

import json

import pytest
from fastapi.testclient import TestClient

from app import engine, store
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_store():
    store.clear()


def new_player() -> str:
    r = client.post("/api/player", json={"display_name": "Tester"})
    assert r.status_code == 201
    return r.json()["player_id"]


def start(player_id: str, is_scam: bool | None = None, monkeypatch=None) -> dict:
    if is_scam is not None:
        monkeypatch.setattr(engine, "assign_is_scam", lambda *a, **k: is_scam)
    r = client.post("/api/round/start", json={"player_id": player_id, "scenario_id": "bank_alert"})
    assert r.status_code == 201, r.text
    return r.json()


def say(round_id: str, text: str) -> dict:
    r = client.post(f"/api/round/{round_id}/message", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def act(round_id: str, action: str, **extra) -> dict:
    r = client.post(f"/api/round/{round_id}/action", json={"action": action, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_scenarios_list():
    pid = new_player()
    body = client.get(f"/api/scenarios?player_id={pid}").json()
    assert body["scenarios"][0]["id"] == "bank_alert"
    assert body["train_your_weakness"] is None


def test_start_round_reveals_nothing():
    rnd = start(new_player())
    text = json.dumps(rnd)
    for secret in ("is_scam", "tactic", "pressure", "authority", "checkable_details"):
        assert secret not in text
    assert rnd["id_card"]["card_last4"] in rnd["opening_message"]["text"]
    assert len(rnd["suggested_replies"]) == 3


def test_scam_round_code_arrives_then_player_gives_it_away():
    rnd = start(new_player())  # a new player's first round is always a scam
    rid = rnd["round_id"]

    t1 = say(rid, "Who is this?")
    assert t1["turn"] == 1 and t1["reply"]["text"] and not t1["ended"]
    assert "tactic" not in json.dumps(t1)

    t2 = say(rid, "ok what do I need to do")
    assert t2["notifications"], "the one-time code should arrive on turn 2"
    code_msg = t2["notifications"][0]["text"]
    code = "".join(ch for ch in code_msg.split("code is")[1] if ch.isdigit())[:6]

    t3 = say(rid, f"here you go {code}")
    assert t3["ended"] and t3["ending"]["code"] == "SCAMMED" and t3["ending"]["is_scam"]

    result = client.get(f"/api/round/{rid}/result").json()
    assert result["explanation"]["type"] == "scam_autopsy"
    assert any(c["player_response"] == "fell_for_it" for c in result["explanation"]["timeline"])
    assert result["transcript"][-1]["note"].startswith("You gave away")


def test_scam_round_verify_gives_call_script_and_updates_radar():
    pid = new_player()
    rid = start(pid)["round_id"]
    say(rid, "How do I know this is really my bank?")
    end = act(rid, "verify")
    assert end["ended"] and end["ending"]["code"] == "OUTSMARTED"
    assert "did not come from us" in json.dumps(end["verification_call"])

    result = client.get(f"/api/round/{rid}/result").json()
    assert result["points"] > 0 and result["xp_earned"] > result["points"]
    assert result["explanation"]["best_decision"].startswith("You verified")
    assert [b["id"] for b in result["new_badges"]] == ["first_escape", "no_mistakes"]

    radar = client.get(f"/api/player/{pid}/radar").json()
    assert len(radar["radar"]) == 6 and radar["xp"] == result["xp_earned"]
    assert client.get(f"/api/scenarios?player_id={pid}").json()["train_your_weakness"]


def test_legit_round_completion_and_lucky_twin(monkeypatch):
    rid = start(new_player(), is_scam=False, monkeypatch=monkeypatch)["round_id"]
    end = say(rid, "NO")
    assert end["ended"] and end["ending"]["code"] == "LUCKY" and not end["ending"]["is_scam"]
    result = client.get(f"/api/round/{rid}/result").json()
    assert result["explanation"]["type"] == "legit_breakdown"
    assert result["explanation"]["scam_twin"]["text"]


def test_legit_round_hang_up_is_false_alarm(monkeypatch):
    rid = start(new_player(), is_scam=False, monkeypatch=monkeypatch)["round_id"]
    assert act(rid, "hang_up")["ending"]["code"] == "FALSE_ALARM"


def test_ask_proof_is_a_turn_with_player_message():
    rid = start(new_player())["round_id"]
    resp = act(rid, "ask_proof")
    assert resp["turn"] == 1 and resp["player_message"]["sender"] == "player"
    assert resp["reply"]["text"] and not resp["ended"]


def test_real_data_is_blocked_and_not_a_turn():
    rid = start(new_player())["round_id"]
    resp = say(rid, "my ssn is 123-45-6789")
    assert resp["blocked"] and resp["turn"] == 0 and resp["reply"] is None


@pytest.mark.parametrize("text", ["", "   ", "x" * 501])
def test_bad_message_length(text):
    rid = start(new_player())["round_id"]
    r = client.post(f"/api/round/{rid}/message", json={"text": text})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_errors_use_contract_shape():
    r = client.post("/api/round/r_nope/message", json={"text": "hi"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "round_not_found"

    rid = start(new_player())["round_id"]
    r = client.get(f"/api/round/{rid}/result")
    assert r.status_code == 409 and r.json()["error"]["code"] == "round_not_ended"

    act(rid, "report")
    r = client.post(f"/api/round/{rid}/message", json={"text": "hi"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "round_ended"


def test_open_link_must_be_from_the_conversation():
    rid = start(new_player())["round_id"]
    r = client.post(f"/api/round/{rid}/action", json={"action": "open_link", "link": "evil.example"})
    assert r.status_code == 400


def test_settings_and_hints():
    pid = new_player()
    r = client.patch(f"/api/player/{pid}/settings", json={"hints": True})
    assert r.json() == {"hints": True, "save_conversations": True}
    rid = start(pid)["round_id"]
    assert say(rid, "who is this")["hint"]["suspicion"] > 0


def test_turn_limit_ends_round():
    rid = start(new_player())["round_id"]
    for _ in range(9):
        assert not say(rid, "hmm tell me more")["ended"]
    last = say(rid, "hmm tell me more")
    assert last["ended"] and last["ending"]["code"] == "ALMOST_SCAMMED"


def test_frontend_is_served():
    assert client.get("/").status_code == 200


def test_test_console_is_served():
    r = client.get("/play")
    assert r.status_code == 200 and "Outsmart test console" in r.text
