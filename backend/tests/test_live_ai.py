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
from app.ai import prompts
from app.ai.live import CharacterOut, LiveAI, check_character
from app.ai.llm import LLM, parse_models
from app.ai.mock import mock_character_move
from app.config import Settings
from app.scenarios import get_scenario, new_id_card


def make_ctx(is_scam: bool = True, code_arrived: bool = True) -> TurnContext:
    scenario = get_scenario("bank_alert")
    card = new_id_card(scenario, random.Random(3))
    state = engine.RoundState(is_scam=is_scam, id_card=card, objective="x")
    return TurnContext(scenario=scenario, state=state, player_text="who is this?", code_arrived=code_arrived)


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
    llm = LLM(Settings(_env_file=None))
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
    ("Log in at harborpoint-secure.com right now.", "suspicious_link", "real-looking website"),
    ("Call me back at 999-382-4710.", "authority", "real-looking number"),
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


@pytest.mark.parametrize("message", [
    "Please confirm your card PIN so we can unlock the account.",
    "What is your home address?",
    "To verify you, reply with your date of birth.",
    "Please provide the expiration date and CVV on your card.",
    "Send me your online banking password now.",  # bank_alert's card has no password
])
def test_contact_cannot_ask_for_things_not_on_the_id_card(message):
    out = CharacterOut(message=message, tactic="credential_request", pressure=60)
    assert check_character(out, make_ctx()) == "asked for something not on the ID card"


@pytest.mark.parametrize("message", [
    "Please read me the one-time code we just sent.",  # bank_alert sends a code, so it's fair game
    "Confirm your email address and the last four digits of your card.",
    "We will never ask for your PIN or home address.",
    "I can send the replacement part to the address on file.",  # tells, doesn't ask
])
def test_contact_can_ask_for_id_card_items(message):
    out = CharacterOut(message=message, tactic="credential_request", pressure=60)
    assert check_character(out, make_ctx()) is None


@pytest.mark.parametrize("message", [
    "Please read the one-time code sent to your phone.",
    "I only need that 6-digit code we texted you.",
    "Text back the code we just sent so I can stop the charge.",
])
def test_contact_cannot_ask_for_the_code_before_it_arrives(message):
    out = CharacterOut(message=message, tactic="credential_request", pressure=60)
    assert check_character(out, make_ctx(code_arrived=False)) == "asked for something not on the ID card"
    assert check_character(out, make_ctx(code_arrived=True)) is None


def test_contact_can_mention_codes_before_one_arrives():
    out = CharacterOut(message="We will never ask for your one-time code.", tactic="trust_building", pressure=20)
    assert check_character(out, make_ctx(code_arrived=False)) is None


def test_prewritten_lines_and_prompt_wait_for_the_code():
    ctx = make_ctx(code_arrived=False)
    for tactic in ("authority", "urgency"):  # credential_request would be next
        engine.record_character_move(ctx.state, tactic)
    assert mock_character_move(ctx).flag != "credential_request"
    assert "one-time code" not in prompts.card_items(ctx)
    assert "don't ask for one" in prompts.character_system(ctx)

    ctx.code_arrived = True
    assert mock_character_move(ctx).flag == "credential_request"
    assert "the one-time code the bank texts them" in prompts.card_items(ctx)


@pytest.mark.parametrize("message", [
    "hi, this is the fraud team. we need to verify you.",
    "This is the fraud team. i need you to verify now.",
    "Pls verify ur account right away.",
    "Can u confirm this purchase?",
    "Your account is locked 🔒 Verify now.",
])
def test_informal_writing_is_rejected(message):
    out = CharacterOut(message=message, tactic="urgency", pressure=60)
    assert check_character(out, make_ctx()) == "informal writing"


@pytest.mark.parametrize("message", [
    "Please send the one-time code from your ID so I can stop the charge.",
    "Read me the card number on your ID card.",
])
def test_contact_cannot_mention_the_id_card(message):
    out = CharacterOut(message=message, tactic="credential_request", pressure=60)
    assert check_character(out, make_ctx()) == "mentioned the ID card"


def test_fake_links_dont_count_as_lowercase():
    out = CharacterOut(message="secure-login.example/verify is our secure page. Please log in now.",
                       tactic="suspicious_link", pressure=60)
    assert check_character(out, make_ctx()) is None


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
    ai = LiveAI(Settings(_env_file=None))
    ai.llm.clients = {"groq": FakeClient([rate_limit()] * 10)}  # every model on it is rate limited
    ctx = make_ctx()
    move = asyncio.run(ai.character_move(ctx))
    assert move.message and move.flag in ctx.version["allowed_tactics"]
    analysis = asyncio.run(ai.analyze(ctx))
    assert analysis.decision_type == "challenge"


def test_live_analyzer_output_is_clamped_and_unknown_flags_dropped():
    reply = json.dumps({"decision_type": "challenge", "suspicion_change": 90, "trust_change": -5,
                        "tactic_recognized": "mind_control", "flag_noticed": None,
                        "mistake": False, "reason": "You asked who they were."})
    ai = LiveAI(Settings(_env_file=None))
    ai.llm.clients = {"groq": FakeClient([reply])}
    ai.analyzer_models = [("groq", "m")]
    analysis = asyncio.run(ai.analyze(make_ctx()))
    assert analysis.suspicion_change == 20 and analysis.tactic_recognized is None


def test_rate_limit_on_one_model_does_not_block_another_on_same_provider():
    groq = FakeClient([rate_limit(), good_scam_reply()])
    out = asyncio.run(llm_with(groq=groq).json_call(
        [("groq", "qwen"), ("groq", "gpt-oss")], "s", "u", CharacterOut))
    assert out is not None and groq.calls == 2


def test_provider_json_rejection_counts_as_a_bad_reply_and_is_retried():
    response = httpx.Response(400, request=httpx.Request("POST", "https://example.invalid"))
    json_error = openai.BadRequestError("Failed to validate JSON", response=response, body=None)
    groq = FakeClient([json_error, good_scam_reply()])
    out = asyncio.run(llm_with(groq=groq).json_call([("groq", "m")], "s", "u", CharacterOut))
    assert out is not None and groq.calls == 2


def test_gpt_oss_models_get_low_reasoning_effort():
    from app.ai.llm import request_kwargs
    assert request_kwargs("openai/gpt-oss-20b", "s", "u", 100)["extra_body"] == {"reasoning_effort": "low"}
    assert "extra_body" not in request_kwargs("qwen/qwen3.8-27b", "s", "u", 100)


# --- Time budget and warm-up ---------------------------------------------------

class SlowClient(FakeClient):
    """Every call takes `delay` seconds (or times out at the given timeout, like the real SDK)."""

    def __init__(self, delay):
        super().__init__([])
        self.delay = delay

    async def _create(self, **kwargs):
        self.calls += 1
        await asyncio.sleep(min(self.delay, kwargs["timeout"]))
        if self.delay > kwargs["timeout"]:
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=good_scam_reply()))])


def test_budget_caps_the_whole_call_when_every_model_is_slow():
    import time as _time
    slow = SlowClient(delay=5)
    llm = llm_with(groq=slow, gemini=SlowClient(delay=5))
    started = _time.monotonic()
    out = asyncio.run(llm.json_call([("groq", "a"), ("groq", "b"), ("gemini", "c")], "s", "u", CharacterOut,
                                    timeout=1.0, budget=1.5))
    assert out is None
    assert _time.monotonic() - started < 2.5  # not 3 models x 1s each


def test_budget_still_allows_a_normal_answer():
    llm = llm_with(groq=SlowClient(delay=0.05))
    assert asyncio.run(llm.json_call([("groq", "a")], "s", "u", CharacterOut, budget=2)) is not None


def test_warm_up_lists_models_and_ignores_failures():
    class ListClient:
        def __init__(self, fail):
            self.fail, self.listed = fail, 0
            self.models = SimpleNamespace(list=self._list)

        async def _list(self):
            self.listed += 1
            if self.fail:
                raise RuntimeError("provider down")
            return []

    good, bad = ListClient(fail=False), ListClient(fail=True)
    llm = llm_with(groq=good, gemini=bad)
    assert asyncio.run(llm.warm_up()) == 1
    assert good.listed == 1 and bad.listed == 1
