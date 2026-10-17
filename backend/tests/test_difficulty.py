"""Difficulty: player level raises it, the prompts change with it, and it's recorded."""

import random

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db, engine, store
from app.ai import prompts
from app.ai.base import TurnContext
from app.ai.mock import mock_character_move
from app.main import app
from app.scenarios import get_scenario, new_id_card

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_store():
    store.clear()


@pytest.mark.parametrize("base,level,expected", [
    (2, 1, 2), (2, 2, 2), (2, 3, 3), (2, 5, 4), (2, 7, 5), (2, 20, 5),  # +1 every 2 levels, max 5
    (1, 1, 1), (1, 3, 2),
])
def test_round_difficulty(base, level, expected):
    assert engine.round_difficulty(base, level) == expected


def player_at_level(level: int) -> str:
    pid = client.post("/api/player", json={}).json()["player_id"]
    player = store.get_player(pid)
    player.xp = engine.xp_threshold(level)
    store.save_player(player)
    return pid


def test_difficulty_rises_with_level_in_the_list_the_round_and_the_logs():
    new, experienced = player_at_level(1), player_at_level(5)
    cards = {p: {c["id"]: c["difficulty"] for c in client.get(f"/api/scenarios?player_id={p}").json()["scenarios"]}
             for p in (new, experienced)}
    assert cards[new]["bank_alert"] == 2 and cards[experienced]["bank_alert"] == 4

    rnd = client.post("/api/round/start", json={"player_id": experienced, "scenario_id": "bank_alert"}).json()
    assert rnd["difficulty"] == 4
    client.post(f"/api/round/{rnd['round_id']}/action", json={"action": "report"})
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.rounds.c.difficulty)).scalar() == 4


def ctx(is_scam: bool, difficulty: int) -> TurnContext:
    scenario = get_scenario("bank_alert")
    state = engine.RoundState(is_scam=is_scam, id_card=new_id_card(scenario, random.Random(1)),
                              objective="x", difficulty=difficulty)
    return TurnContext(scenario=scenario, state=state, code_arrived=True)


@pytest.mark.parametrize("difficulty", [1, 2, 3, 4, 5])
def test_prompts_describe_the_difficulty(difficulty):
    scam = prompts.character_system(ctx(True, difficulty))
    legit = prompts.character_system(ctx(False, difficulty))
    assert f"Difficulty {difficulty} of 5: {prompts.SCAM_STYLE[difficulty]}" in scam
    assert prompts.LEGIT_STYLE[difficulty] in legit
    assert "never ask for secrets or money" in legit  # honesty doesn't depend on difficulty
    assert "typo" not in scam + legit and "informal" not in scam + legit  # everyone writes properly
    assert prompts.WRITING_RULES in scam and prompts.WRITING_RULES in legit


def test_prompt_lists_only_this_rounds_id_card_items():
    bank = prompts.character_system(ctx(True, 3))
    assert "the one-time code the bank texts them" in bank
    assert "password" not in prompts.card_items(ctx(True, 3))  # bank_alert's card has no password
    job = get_scenario("job_offer")
    state = engine.RoundState(is_scam=True, id_card=new_id_card(job, random.Random(1)), objective="x")
    assert "online banking password" in prompts.card_items(TurnContext(scenario=job, state=state))


def test_fallback_scammer_is_patient_at_high_difficulty():
    easy, hard = ctx(True, 2), ctx(True, 4)
    for c in (easy, hard):
        engine.record_character_move(c.state, "authority")
    assert mock_character_move(easy).flag != "trust_building"
    assert mock_character_move(hard).flag == "trust_building"
