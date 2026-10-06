"""AI Explainer: it may only reword facts the engine decided, and bad output falls back."""

import asyncio
import json
from types import SimpleNamespace

from app import game, progress, store
from app.ai import explainer
from app.ai.base import ExplainerText
from app.ai.live import LiveAI
from app.ai.mock import MockAI
from app.config import Settings
from app.explain import build_result, explain_request


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls += 1
        content = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class CountingAI(MockAI):
    def __init__(self, words=None):
        self.words = words
        self.calls = 0

    async def explain(self, request):
        self.calls += 1
        return self.words


def finished_round():
    """A short scam round played to the end with the mock AI: opening, one reply, verify."""
    store.clear()
    player = progress.Player(id="p_x")
    store.save_player(player)
    ai = MockAI()
    start = asyncio.run(game.start_round(player, "bank_alert", ai))
    rnd = store.get_round(start.round_id)
    asyncio.run(game.send_message(rnd, "Who is this?", ai))
    asyncio.run(game.do_action(rnd, "verify", None, ai))
    return rnd


def live_ai(replies) -> LiveAI:
    ai = LiveAI(Settings(_env_file=None))
    ai.llm.clients = {"groq": FakeClient(replies)}
    ai.explainer_models = [("groq", "m")]
    return ai


# --- What the Explainer is shown ----------------------------------------------------

def test_request_contains_the_engines_facts():
    rnd = finished_round()
    req = explain_request(rnd)
    assert req.is_scam and req.ending_title == "Outsmarted"
    assert req.flags == ["authority", "trust_building"]
    text = explainer.explainer_user(req)
    assert "[0] CONTACT (authority)" in text and "[1] YOU: Who is this?" in text
    assert '"timeline": {"authority": "...", "trust_building": "..."}' in text


# --- Applying the words -----------------------------------------------------------------

def test_words_replace_summaries_notes_and_best_decision():
    rnd = finished_round()
    words = ExplainerText(
        timeline={"authority": "They claimed to be the Buckeye fraud team so you'd trust the text."},
        messages={0: "This opening text pretended to come from your bank."},
    )
    result = build_result(rnd, words)
    cards = {c.flag.id: c.summary for c in result.explanation.timeline}
    assert cards["authority"].startswith("They claimed to be the Buckeye")
    assert cards["trust_building"] == "They acted friendly and helpful so you'd lower your guard."  # engine fallback
    assert result.transcript[0].note == "This opening text pretended to come from your bank."
    # facts, including the best decision, never change
    plain = build_result(rnd)
    assert (result.ending, result.points, result.tip) == (plain.ending, plain.points, plain.tip)
    assert result.explanation.best_decision == plain.explanation.best_decision
    assert [c.player_response for c in result.explanation.timeline] == [
        c.player_response for c in plain.explanation.timeline]


def test_mock_mode_keeps_the_engine_text():
    rnd = finished_round()
    result = asyncio.run(game.get_result(rnd, MockAI()))
    assert result == build_result(rnd)


def test_explainer_runs_once_per_round():
    rnd = finished_round()
    ai = CountingAI()
    asyncio.run(game.get_result(rnd, ai))
    asyncio.run(game.get_result(rnd, ai))
    assert ai.calls == 1


# --- Checking the AI's output --------------------------------------------------------

def good_reply(**changes):
    reply = {
        "timeline": {"authority": "They said they were Buckeye's fraud team.",
                     "trust_building": "They said they were here to protect your money."},
        "messages": {"0": "This text pretended to be a fraud alert from your bank.",
                     "1": "This is your message, which shouldn't get a note.",
                     "2": "They acted understanding so you'd keep talking."},
    }
    reply.update(changes)
    return json.dumps(reply)


def test_live_explainer_keeps_only_known_flags_and_contact_messages():
    rnd = finished_round()
    req = explain_request(rnd)
    reply = json.loads(good_reply())
    reply["timeline"]["made_up_flag"] = "Should be dropped."
    words = asyncio.run(live_ai([json.dumps(reply)]).explain(req))
    assert set(words.timeline) == {"authority", "trust_building"}
    assert 1 not in words.messages  # index 1 is the player's own message
    assert words.messages[0].startswith("This text pretended")


def test_live_explainer_rejects_unsafe_text_and_falls_back():
    rnd = finished_round()
    bad = good_reply(timeline={"authority": "They wanted you to log in at buckeyebank.com."})
    ai = live_ai([bad, bad])
    assert asyncio.run(ai.explain(explain_request(rnd))) is None


def test_explainer_is_not_asked_to_judge_the_player():
    text = explainer.explainer_user(explain_request(finished_round()))
    assert "best_decision" not in text and "best decision" not in text.lower()
    # how the player responded is shown by the engine, so the Explainer isn't told (or tempted)
    assert "resisted" not in text and "fell for" not in text
    assert 'never "he" or "she"' in explainer.explainer_system()
