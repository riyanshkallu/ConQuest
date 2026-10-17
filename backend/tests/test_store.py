"""Saving to the database: progress survives restarts, rounds are logged, privacy setting respected."""

import dataclasses
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db, store
from app.main import app
from app.progress import Player
from app.store import _PLAYER_COLUMNS

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_store():
    store.clear()


def play_a_round(settings: dict | None = None) -> tuple[str, str]:
    pid = client.post("/api/player", json={"display_name": "Tester"}).json()["player_id"]
    if settings:
        client.patch(f"/api/player/{pid}/settings", json=settings)
    rid = client.post("/api/round/start", json={"player_id": pid, "scenario_id": "bank_alert"}).json()["round_id"]
    client.post(f"/api/round/{rid}/message", json={"text": "Who is this?"})
    client.post(f"/api/round/{rid}/action", json={"action": "verify"})
    return pid, rid


def rows(table):
    with db.get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(select(table)).mappings()]


def test_progress_survives_a_restart():
    pid, _ = play_a_round()
    before = client.get(f"/api/player/{pid}/radar").json()
    assert before["xp"] > 0 and before["badges"][0]["earned"]

    store.forget_cache()  # the server restarted: memory is gone, the database isn't

    after = client.get(f"/api/player/{pid}/radar").json()
    assert after == before
    # and the player can keep playing: the second round counts on top of the first
    rid = client.post("/api/round/start", json={"player_id": pid, "scenario_id": "bank_alert"}).json()["round_id"]
    client.post(f"/api/round/{rid}/action", json={"action": "report"})
    assert client.get(f"/api/player/{pid}/radar").json()["xp"] > after["xp"]


@pytest.mark.parametrize("url", ["", "sqlite:///outsmart.db", "postgresql://app:secret@db.example:5432/postgres"])
def test_clear_refuses_anything_but_a_test_database(monkeypatch, url):
    # "" is what a script gets when it drops DATABASE_URL: the app then falls back to .env (real data)
    monkeypatch.setattr(store, "get_settings", lambda: SimpleNamespace(database_url=url))
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    pid = client.post("/api/player", json={}).json()["player_id"]
    with pytest.raises(RuntimeError, match="only runs on a test database"):
        store.clear()
    assert store.get_player(pid)  # nothing was cleared, not even the memory cache


def family_player(pid: str) -> bool:
    badges = client.get(f"/api/player/{pid}/radar").json()["badges"]
    return next(b["earned"] for b in badges if b["id"] == "family_player")


def test_second_profile_on_a_device_earns_family_player_for_both():
    first = client.post("/api/player", json={}).json()["player_id"]
    assert not family_player(first)

    r = client.post("/api/player", json={"display_name": "Grandpa", "other_player_ids": [first, first, "p_nobody"]})
    assert r.status_code == 201
    second = r.json()["player_id"]

    store.forget_cache()
    assert family_player(first) and family_player(second)


def test_family_player_needs_a_real_other_profile():
    pid = client.post("/api/player", json={"other_player_ids": ["p_nobody"]}).json()["player_id"]
    assert not family_player(pid)
    r = client.post("/api/player", json={"other_player_ids": [f"p_{i}" for i in range(11)]})
    assert r.status_code == 400


def test_settings_and_reset_are_saved():
    pid, _ = play_a_round()
    client.patch(f"/api/player/{pid}/settings", json={"hints": True})
    client.post(f"/api/player/{pid}/reset")
    store.forget_cache()
    radar = client.get(f"/api/player/{pid}/radar").json()
    assert radar["xp"] == 0 and not any(b["earned"] for b in radar["badges"])
    assert store.get_player(pid).hints is True


def test_a_round_in_progress_survives_a_restart():
    pid = client.post("/api/player", json={}).json()["player_id"]
    start = client.post("/api/round/start", json={"player_id": pid, "scenario_id": "bank_alert"}).json()
    rid = start["round_id"]
    client.post(f"/api/round/{rid}/message", json={"text": "Who is this?"})
    before = store.get_round(rid)

    store.forget_cache()  # Render restarted the server mid-round

    r = client.post(f"/api/round/{rid}/message", json={"text": "How do I know this is real?"})
    assert r.status_code == 200 and r.json()["turn"] == 2  # the first turn still counts
    after = store.get_round(rid)
    assert after.state.id_card == before.state.id_card and after.state.is_scam == before.state.is_scam
    assert [m["text"] for m in after.transcript][:3] == [m["text"] for m in before.transcript][:3]

    client.post(f"/api/round/{rid}/action", json={"action": "verify"})
    result = client.get(f"/api/round/{rid}/result").json()
    store.forget_cache()
    assert client.get(f"/api/round/{rid}/result").json() == result  # same explanation, not a new one
    assert len(rows(db.rounds)) == 1  # finished once, logged once


def test_unknown_round_is_still_not_found():
    assert client.post("/api/round/r_nope/message", json={"text": "hi"}).status_code == 404


def test_finished_rounds_are_logged_with_messages():
    pid, rid = play_a_round()
    (rnd,) = rows(db.rounds)
    assert rnd["id"] == rid and rnd["player_id"] == pid
    assert rnd["ending"] == "OUTSMARTED" and rnd["is_scam"] and rnd["turns"] == 1
    assert rnd["details"]["bank"]  # the round's generated names are kept
    msgs = sorted(rows(db.messages), key=lambda m: m["idx"])
    assert [m["sender"] for m in msgs][:3] == ["contact", "player", "contact"]
    assert msgs[0]["flag"] == "authority"
    assert msgs[1]["analysis"]["decision_type"] == "challenge"


def test_no_messages_saved_when_the_player_turns_saving_off():
    play_a_round({"save_conversations": False})
    assert len(rows(db.rounds)) == 1  # anonymous summary only
    assert rows(db.messages) == []


def test_blocked_real_data_is_never_saved():
    pid = client.post("/api/player", json={}).json()["player_id"]
    rid = client.post("/api/round/start", json={"player_id": pid, "scenario_id": "bank_alert"}).json()["round_id"]
    client.post(f"/api/round/{rid}/message", json={"text": "my ssn is 123-45-6789"})
    client.post(f"/api/round/{rid}/action", json={"action": "hang_up"})
    assert not any("123-45-6789" in m["text"] for m in rows(db.messages))


def test_unfinished_rounds_are_not_logged():
    pid = client.post("/api/player", json={}).json()["player_id"]
    client.post("/api/round/start", json={"player_id": pid, "scenario_id": "bank_alert"})
    assert rows(db.rounds) == []


def test_health_reports_the_database():
    assert client.get("/api/health").json()["database"] == "ok"


def test_every_player_field_is_saved():
    for f in dataclasses.fields(Player):
        assert f.name in _PLAYER_COLUMNS or f.name in ("id", "radar"), f"{f.name} isn't saved"
        if f.name in _PLAYER_COLUMNS:
            assert f.name in db.players.c, f"db.players is missing {f.name}"


@pytest.mark.parametrize("url", [
    "postgresql://postgres.abc:pw@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    "postgres://postgres.abc:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres",
])
def test_supabase_urls_use_the_psycopg_driver(url):
    engine = db.make_engine(url)  # no connection is made until first use
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.dialect.name == "postgresql"


def test_local_default_is_a_sqlite_file():
    engine = db.make_engine("")
    assert engine.url.drivername == "sqlite" and engine.url.database.endswith("outsmart.db")
