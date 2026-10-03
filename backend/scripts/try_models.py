"""Oct 1 model test: compare free models on speed, valid JSON, rule-following and refusals.

Run from backend/ after putting your free keys in .env:
  .venv/Scripts/python scripts/try_models.py              # the models listed in .env / config
  .venv/Scripts/python scripts/try_models.py --list       # every model your keys can use
  .venv/Scripts/python scripts/try_models.py groq:openai/gpt-oss-120b gemini:gemini-2.5-flash

Each model plays the same short scenes several times. A good pick for the character is
fast (under ~3s), always valid, and never refuses. The analyzer should be under ~1s.
"""

from __future__ import annotations

import asyncio
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import engine  # noqa: E402
from app.ai import prompts  # noqa: E402
from app.ai.base import TurnContext  # noqa: E402
from app.ai.live import AnalyzerOut, CharacterOut, check_character  # noqa: E402
from app.ai.llm import LLM, _extract_json, parse_models, request_kwargs  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.scenarios import get_scenario, new_id_card  # noqa: E402

TRIALS = 2
# Free tiers allow ~8,000 tokens/minute per model and each call is ~600 tokens, so pace the calls.
PAUSE_SECONDS = 5
REFUSAL_WORDS = ("i can't", "i cannot", "i'm not able", "i am not able", "i won't", "as an ai", "i'm sorry, but")


def scene(is_scam: bool, player_lines: list[str], code_now: bool = False, decision: str = "neutral") -> TurnContext:
    scenario = get_scenario("bank_alert")
    card = new_id_card(scenario, random.Random(7))
    version = scenario.version(is_scam)
    state = engine.RoundState(is_scam=is_scam, id_card=card, objective=version["objective"])
    engine.record_character_move(state, version["opening"]["flag"])
    transcript = [{"sender": "contact", "text": "Buckeye Federal Fraud Alert: ... card ending " + card.card_last4}]
    for line in player_lines:
        state.turns += 1
        transcript.append({"sender": "player", "text": line})
    return TurnContext(scenario=scenario, state=state, transcript=transcript,
                       player_text=player_lines[-1], last_decision=decision, code_just_sent=code_now)


CHARACTER_SCENES = {
    "scam, opening": scene(True, ["Who is this?"], decision="challenge"),
    "scam, code sent": scene(True, ["ok", "what do I need to do?"], code_now=True, decision="partial_compliance"),
    "scam, pushback": scene(True, ["I'm going to call the number on my card."], decision="safe_verification"),
    "legit, opening": scene(False, ["How do I know this is really you?"], decision="challenge"),
}
ANALYZER_SCENES = {
    "challenge": scene(True, ["How do I know this is really my bank?"]),
    "safe_verification": scene(True, ["I'll call the number on the back of my card instead."]),
    "partial_compliance": scene(True, ["ok sure, what do you need?"]),
}


async def one_call(client, model: str, system: str, user: str, max_tokens: int):
    await asyncio.sleep(PAUSE_SECONDS)
    started = time.monotonic()
    try:
        resp = await client.chat.completions.create(**request_kwargs(model, system, user, max_tokens), timeout=20)
        return resp.choices[0].message.content or "", time.monotonic() - started, None
    except Exception as exc:  # report every failure kind in the table
        return "", time.monotonic() - started, f"{type(exc).__name__}: {str(exc)[:80]}"


async def test_model(llm: LLM, provider: str, model: str) -> None:
    client = llm.clients.get(provider)
    if client is None:
        print(f"\n{provider}:{model}: no {provider.upper()}_API_KEY in .env, skipped")
        return
    print(f"\n=== {provider}:{model} ===")

    times, problems, refusals = [], [], 0
    for name, ctx in CHARACTER_SCENES.items():
        for _ in range(TRIALS):
            text, secs, err = await one_call(client, model, prompts.character_system(ctx),
                                             prompts.character_user(ctx), 400)
            if err:
                problems.append(f"{name}: {err}")
                continue
            times.append(secs)
            if any(w in text.lower() for w in REFUSAL_WORDS):
                refusals += 1
            try:
                out = CharacterOut.model_validate_json(_extract_json(text))
                problem = check_character(out, ctx)
            except Exception:
                problem = "invalid JSON"
            if problem:
                problems.append(f"{name}: {problem}: {text[:90]!r}")
        print(f"  character sample ({name}): {text[:140]!r}")
    _report("character", times, TRIALS * len(CHARACTER_SCENES), problems, refusals)

    times, problems = [], []
    for expected, ctx in ANALYZER_SCENES.items():
        for _ in range(TRIALS):
            text, secs, err = await one_call(client, model, prompts.analyzer_system(ctx),
                                             prompts.analyzer_user(ctx), 300)
            if err:
                problems.append(f"{expected}: {err}")
                continue
            times.append(secs)
            try:
                out = AnalyzerOut.model_validate_json(_extract_json(text))
                if out.decision_type != expected:
                    problems.append(f"expected {expected}, got {out.decision_type}")
            except Exception:
                problems.append(f"{expected}: invalid JSON: {text[:90]!r}")
    _report("analyzer", times, TRIALS * len(ANALYZER_SCENES), problems, 0)


def _report(role: str, times: list[float], total: int, problems: list[str], refusals: int) -> None:
    ok = total - len(problems)
    avg = statistics.mean(times) if times else float("nan")
    worst = max(times) if times else float("nan")
    print(f"  {role:9} ok {ok}/{total}   avg {avg:.1f}s   slowest {worst:.1f}s   refusals {refusals}")
    for p in problems[:5]:
        print(f"    - {p}")


async def list_models(llm: LLM) -> None:
    for provider, client in llm.clients.items():
        models = await client.models.list()
        print(f"\n{provider}:")
        for m in sorted(m.id for m in models.data):
            print(f"  {provider}:{m}")


async def main() -> None:
    settings = get_settings()
    llm = LLM(settings)
    if not llm.clients:
        sys.exit("No API keys found. Copy .env.example to .env and add GROQ_API_KEY and/or GEMINI_API_KEY.")
    args = sys.argv[1:]
    if args == ["--list"]:
        await list_models(llm)
        return
    targets = parse_models(",".join(args)) if args else list(dict.fromkeys(
        parse_models(settings.character_models) + parse_models(settings.analyzer_models)))
    for provider, model in targets:
        await test_model(llm, provider, model)


if __name__ == "__main__":
    asyncio.run(main())
