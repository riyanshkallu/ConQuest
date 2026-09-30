# Backend

Python 3.11+ and FastAPI. It serves the API described in [../api.md](../api.md) and the
files in `../frontend/`.

## Setup (Windows, from `backend/`)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env          # then edit .env
```

## Run

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload
```

- Game: http://127.0.0.1:8000
- Clickable API docs: http://127.0.0.1:8000/docs

With `AI_PROVIDER=mock` (the default) everything works with no keys, using the pre-written
lines. Set `AI_PROVIDER=live` and add a free Groq and/or Gemini key to use real AI.

## Test

```bash
.venv/Scripts/python -m pytest              # engine, API and AI-validation tests, no keys needed
.venv/Scripts/python scripts/try_models.py  # compare free models (needs keys)
```

## How it fits together

```
app/
  main.py        HTTP routes (thin): validate input, call game.py, return schemas
  game.py        Runs a turn: blocker -> trap check -> analyzer -> engine -> character
  engine.py      The rules. The ONLY thing that decides endings and points. No web/AI code.
  progress.py    XP, levels, streaks, Scam Radar, badges
  explain.py     Scam Autopsy / Legit Breakdown / flagged transcript from engine facts
  scenarios.py   Loads data/scenarios/*.json, builds the fictional ID card
  store.py       Players and rounds (in memory for now, Supabase later)
  schemas.py     Pydantic request/response models, matching api.md
  flags.py       Fixed red/green flag lists, radar categories, tips
  config.py      Settings from environment variables / .env
  ai/
    mock.py      Keyword analyzer + pre-written lines (mock mode AND the fallback)
    llm.py       Free-tier provider chain (Groq, then Gemini), JSON validation, retry
    live.py      Analyzer and Character on real models, with the character rules
    prompts.py   The prompts
data/scenarios/  One JSON file per scam/legit scenario pair
```

**Key rule:** the AI writes the conversation, but only `engine.py` decides who wins.

## Free-tier notes

- Each chat turn is 2 AI calls, so a 10-turn round is about 20. If Groq returns "rate limited",
  that provider is skipped for 20 seconds and Gemini is used; if both fail, the pre-written
  lines keep the round going.
- Groq's larger models allow about 12,000 tokens per minute on the free tier, which is enough
  for a few players at once but not a whole classroom. Keep prompts short.
