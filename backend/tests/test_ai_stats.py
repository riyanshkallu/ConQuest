"""AI health stats: live vs fallback answers are counted, shown in /api/health and saved per round."""

import asyncio
import json
import random
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db, engine, store
from app.ai import stats
from app.ai.base import TurnContext
from app.ai.live import LiveAI
from app.config import Settings
from app.main import app
from app.scenarios import get_scenario, new_id_card

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    store.clear()
    stats.reset()


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


def ctx():
    scenario = get_scenario("bank_alert")
    state = engine.RoundState(is_scam=True, id_card=new_id_card(scenario, random.Random(1)), objective="x")
    return TurnContext(scenario=scenario, state=state, player_text="who is this?")


def live_ai(replies):
    ai = LiveAI(Settings(_env_file=None))
    ai.llm.clients = {"groq": FakeClient(replies)}
    ai.analyzer_models = ai.character_models = [("groq", "m")]
    return ai


def test_live_answers_are_marked_live_and_fallbacks_are_not():
    good_move = json.dumps({"message": "This is the fraud team. Please confirm now.", "tactic": "urgency", "pressure": 50})
    good_analysis = json.dumps({"decision_type": "challenge", "suspicion_change": 5, "trust_change": 0,
                                "tactic_recognized": None, "flag_noticed": None, "mistake": False, "reason": "You asked."})
    ai = live_ai([good_move, good_analysis])
    assert asyncio.run(ai.character_move(ctx())).live is True
    assert asyncio.run(ai.analyze(ctx())).live is True

    broken = live_ai(["not json", "still not json", "nope", "nope"])
    assert asyncio.run(broken.character_move(ctx())).live is False   # pre-written line
    assert asyncio.run(broken.analyze(ctx())).live is False          # keyword rules


def test_health_and_round_log_count_the_answers():
    pid = client.post("/api/player", json={}).json()["player_id"]
    rid = client.post("/api/round/start", json={"player_id": pid, "scenario_id": "bank_alert"}).json()["round_id"]
    client.post(f"/api/round/{rid}/message", json={"text": "who is this?"})
    client.post(f"/api/round/{rid}/action", json={"action": "verify"})

    turns = client.get("/api/health").json()["ai_turns"]
    assert turns["by_role"]["analyzer"] == {"live": 0, "fallback": 1}     # mock mode: all fallback
    assert turns["by_role"]["character"] == {"live": 0, "fallback": 1}
    assert turns["by_role"]["generator"]["fallback"] == 1
    assert turns["fallback"] >= 3

    with db.get_engine().connect() as conn:
        row = conn.execute(select(db.round_ai).where(db.round_ai.c.round_id == rid)).mappings().one()
    assert (row["live"], row["fallback"]) == (0, 2)
