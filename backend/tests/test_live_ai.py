"""Tests for the live AI layer using fake clients: no network, no API keys."""

import asyncio
import json
import random
from types import SimpleNamespace

import httpx
import openai
import pytest

from app import engine
from app.ai.base import TurnContext
from app.ai.live import CharacterOut, LiveAI, check_character
from app.ai.llm import LLM, parse_models
from app.config import Settings
from app.scenarios import get_scenario, new_id_card


def make_ctx(is_scam: bool = True) -> TurnContext:
    scenario = get_scenario("bank_alert")
    card = new_id_card(scenario, random.Random(3))
    state = engine.RoundState(is_scam=is_scam, id_card=card, objective="x")
    return TurnContext(scenario=scenario, state=state, player_text="who is this?")


class FakeClient:
    """Stands in for AsyncOpenAI. Each call pops the next scripted reply (a string or an exception)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


def rate_limit() -> openai.RateLimitError:
    response = httpx.Response(429, request=httpx.Request("POST", "https://example.invalid"))
    return openai.RateLimitError("rate limited", response=response, body=None)


def llm_with(**clients) -> LLM:
    llm = LLM(Settings(groq_api_key="", gemini_api_key=""))
    llm.clients = clients
    return llm


def good_scam_reply(msg="This is the fraud team. We need to verify you right away.", tactic="urgency"):
    return json.dumps({"message": msg, "tactic": tactic, "pressure": 70})


# --- parse_models ----------------------------------------------------------

def test_parse_models_skips_unknown_providers():
    assert parse_models("groq:a, gemini:b ,nope:c,groq:") == [("groq", "a"), ("gemini", "b")]


# --- Character rules ------------------------------------------------------

def test_valid_scam_message_passes():
    assert check_character(CharacterOut.model_validate_json(good_scam_reply()), make_ctx()) is None


@pytest.mark.parametrize("message,tactic,problem", [
    ("word " * 71, "urgency", "too long"),
    ("Act now please.", "sexual_content", "not allowed"),
    ("Log in at buckeye-secure.com right now.", "suspicious_link", "real-looking website"),
    ("Call me back at 614-292-1234.", "authority", "real-looking number"),
    ("What's your SSN?", "credential_request", "blocked word"),
])
def test_bad_scam_messages_are_rejected(message, tactic, problem):
    out = CharacterOut(message=message, tactic=tactic, pressure=50)
    assert problem in check_character(out, make_ctx())


def test_scammer_cannot_say_the_code():
    ctx = make_ctx()
    out = CharacterOut(message=f"Is your code {ctx.state.id_card.verification_code}?", tactic="credential_request")
    assert check_character(out, ctx) == "mentioned the code itself"


def test_legit_contact_cannot_ask_for_a_code_but_can_warn_about_one():
    ctx = make_ctx(is_scam=False)
    asks = CharacterOut(message="Please text us the code we sent you.", green_flag="checkable_details")
    warns = CharacterOut(message="Please don't send us any codes. Reply YES or NO.", green_flag="no_credentials_asked")
    assert check_character(asks, ctx) == "legit contact asked for a secret"
    assert check_character(warns, ctx) is None


# --- Provider chain -------------------------------------------------------

def test_rate_limited_provider_falls_through_to_next():
    groq, gemini = FakeClient([rate_limit()]), FakeClient([good_scam_reply()])
    llm = llm_with(groq=groq, gemini=gemini)
    out = asyncio.run(llm.json_call([("groq", "m1"), ("gemini", "m2")], "sys", "user", CharacterOut))
    assert out.tactic == "urgency" and gemini.calls == 1

    # groq is now cooling down, so the next call goes straight to gemini
    gemini.replies.append(good_scam_reply())
    asyncio.run(llm.json_call([("groq", "m1"), ("gemini", "m2")], "sys", "user", CharacterOut))
    assert groq.calls == 1


def test_bad_reply_is_regenerated_once_then_gives_up():
    groq = FakeClient(["not json", "still not json", good_scam_reply()])
    gemini = FakeClient([good_scam_reply()])
    out = asyncio.run(llm_with(groq=groq, gemini=gemini).json_call(
        [("groq", "m"), ("gemini", "m")], "s", "u", CharacterOut))
    assert out is None and groq.calls == 2 and gemini.calls == 0


def test_json_inside_code_fences_is_accepted():
    groq = FakeClient(["```json\n" + good_scam_reply() + "\n```"])
    out = asyncio.run(llm_with(groq=groq).json_call([("groq", "m")], "s", "u", CharacterOut))
    assert out is not None


def test_live_ai_falls_back_to_prewritten_lines_when_all_models_fail():
    ai = LiveAI(Settings(groq_api_key="", gemini_api_key=""))
    ai.llm.clients = {"groq": FakeClient([rate_limit()])}
    ctx = make_ctx()
    move = asyncio.run(ai.character_move(ctx))
    assert move.message and move.flag in ctx.version["allowed_tactics"]
    analysis = asyncio.run(ai.analyze(ctx))
    assert analysis.decision_type == "challenge"


def test_live_analyzer_output_is_clamped_and_unknown_flags_dropped():
    reply = json.dumps({"decision_type": "challenge", "suspicion_change": 90, "trust_change": -5,
                        "tactic_recognized": "mind_control", "flag_noticed": None,
                        "mistake": False, "reason": "You asked who they were."})
    ai = LiveAI(Settings(groq_api_key="", gemini_api_key=""))
    ai.llm.clients = {"groq": FakeClient([reply])}
    ai.analyzer_models = [("groq", "m")]
    analysis = asyncio.run(ai.analyze(make_ctx()))
    assert analysis.suspicion_change == 20 and analysis.tactic_recognized is None
