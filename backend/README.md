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
.venv/Scripts/python scripts/adversarial.py http://127.0.0.1:8000  # try to break a running server
```

`adversarial.py` throws the plan's attack list at a running server (gibberish, prompt injection,
insults, harmful requests, "I know you're a scammer", the code hidden in a sentence, real card
numbers, double taps) and marks anything that broke with ✗. Rerun it after changing a prompt.
It uses about 70 AI calls. Run the server with a throwaway database
(`DATABASE_URL=sqlite:///test.db`) so attack rounds don't end up in your real Supabase data.

## Deploy (Render, free)

`render.yaml` in the repo root describes the service, so setup is mostly clicking:

1. On render.com, sign in with GitHub and allow access to the `ConQuest` repo.
2. **New > Blueprint**, pick the repo and the `main` branch. Render reads `render.yaml`.
3. When asked, paste `GROQ_API_KEY` and `GEMINI_API_KEY` (the same values as your `.env`).
4. Click **Apply**. The first build takes a few minutes. The app is then live at
   `https://conquestgame.onrender.com` (Render may add a suffix if the name is taken).
5. Check `https://<your-url>/api/health`. It should say `"ai_provider": "live"`.

Every push to `main` redeploys automatically. Rounds in progress are saved to the database
after every turn (the `live_rounds` table), so a redeploy, restart or sleep doesn't end them.

**Save progress (Supabase, free):** without a database, Render's disk is wiped on every
redeploy, and with it every player's XP and Scam Radar.

1. On supabase.com, create a free project (name it `outsmart`). Save the database password it
   asks for. Pick the region closest to your Render service's region.
2. Click **Connect** and copy the **Session pooler** connection string. Render's free plan can't
   reach the direct connection, which is IPv6-only. Replace `[YOUR-PASSWORD]` with your password.
3. In Render, open the service, go to **Environment**, add `DATABASE_URL` with that string, and save.
   Render redeploys.
4. Check `/api/health`. It should say `"database": "ok"`. The app creates its four tables
   (`players`, `radar`, `rounds`, `messages`) on first start, with row level security turned on so
   Supabase's public web API can't read them.

Free Supabase projects pause after 7 days with no activity. The keep-awake ping below also
touches the database, which keeps it active.

**Keep it awake:** free Render services sleep after 15 minutes with no visitors, and the first
visit after that takes about a minute. On uptimerobot.com (free), add an HTTP monitor for
`https://<your-url>/api/health` every 5 minutes. One always-on service uses about 744 of the 750
free hours a month, so don't run a second free Render service in the same account.

## How it fits together

```
app/
  main.py        HTTP routes (thin): validate input, call game.py, return schemas
  game.py        Runs a turn: blocker -> trap check -> analyzer -> engine -> character
  engine.py      The rules. The ONLY thing that decides endings and points. No web/AI code.
  progress.py    XP, levels, streaks, Scam Radar, badges
  explain.py     Scam Autopsy / Legit Breakdown / flagged transcript from engine facts
  scenarios.py   Loads data/scenarios/*.json, builds the fictional ID card
  store.py       Players (database + cache), rounds in progress (memory), finished-round logs
  db.py          Database connection and the four tables (SQLite locally, Supabase in production)
  schemas.py     Pydantic request/response models, matching api.md
  flags.py       Fixed red/green flag lists, radar categories, tips
  config.py      Settings from environment variables / .env
  ai/
    mock.py      Keyword analyzer + pre-written lines (mock mode AND the fallback)
    llm.py       Free-tier provider chain (Groq, then Gemini), JSON validation, retry
    live.py      Analyzer and Character on real models, with the character rules
    prompts.py   The prompts
    generator.py Scenario Generator: fresh fictional names each round, safety-checked
data/scenarios/  One JSON file per scam/legit scenario pair
```

**Fresh details every round.** Each scenario file has a `generate` section listing what can
change. At round start the AI invents new names (bank, store, recruiter, cousin, dog...) and the
code randomizes numbers and fictional phone numbers. Every AI name is checked: no real banks or
brands, no clash with the player's name, no digits or web addresses. If the check fails or the AI
is slow (4s limit), the round uses the hand-written names, so it never blocks play.

**Key rule:** the AI writes the conversation, but only `engine.py` decides who wins.

## Recording the demo video

Demo mode lets you choose scam or legit for a round, so you can record the plan's "same first
message, completely different conversation" shot.

1. In Render, go to **Environment** and add `DEMO_KEY` with any secret word (for example a long
   random string). Never put it in the repo. Without it, demo mode is off.
2. Open the game with the key in the address:
   `https://conquestgame.onrender.com/?demo=YOURKEY&force=scam&seed=7`, record the scam round,
   then open it again with `force=legit&seed=7` for the real one. The same `seed` gives the same
   bank, amount and card ending, so the two opening texts match.
3. Demo rounds are saved with `"demo": true` in their details, so they're easy to tell apart.

## Reliability

- **Rate limits** (`app/ratelimit.py`) protect the free AI quota: 30 new players per IP per hour,
  30 rounds per player per hour, 200 rounds per IP per hour (a whole class shares one school IP).
  Over the limit returns `429 rate_limited` with `Retry-After`. Change them in `.env`
  (`PLAYERS_PER_IP_PER_HOUR`, `ROUNDS_PER_PLAYER_PER_HOUR`, `ROUNDS_PER_IP_PER_HOUR`).
- **Time budgets** cap each AI role across every model and retry (analyzer 6s, character 10s,
  generator 5s, explainer 12s). If every provider is slow at once, the turn uses the pre-written
  lines instead of making the player wait.
- **Warm-up**: in live mode the server opens its AI connections at startup and every 4 minutes
  (listing models costs no tokens), so the first round after a quiet spell starts in about 0.5-1s
  instead of 1.5-2s.
- **AI health**: `/api/health` shows `ai_turns`, how many answers came from a live model vs the
  fallback lines since startup, per role. If `fallback` climbs, a free-tier limit is probably being
  hit. Each finished round's counts are saved in the `round_ai` table.

## Free-tier notes

Models were picked on 2026-09-30 with `scripts/try_models.py` (every model: valid JSON on
every character reply, no refusals, all under 1 second):

| Role | Models, in fallback order | Why |
| --- | --- | --- |
| AI Character | `groq:qwen/qwen3.8-27b`, `groq:openai/gpt-oss-120b`, `gemini:gemini-3.5-flash-lite` | Qwen adapted best when the player pushed back |
| Player Analyzer | `groq:openai/gpt-oss-20b`, `gemini:gemini-3.5-flash-lite` | 6/6 correct, and a different model from the character, so they don't share a quota |

- Measured in the full game with live AI: about **0.6 to 0.7 seconds per turn**, well under the plan's 4-second target.
- Groq's free limits are **per model**: 1,000 requests/day and 8,000 tokens/minute. Each call is
  about 600 tokens, so one model handles roughly 13 calls a minute. Splitting the two roles
  across two models doubles that, and a 10-turn round uses about 10 calls per model. That's
  roughly 100 rounds a day on Groq alone, before Gemini.
- If a model returns "rate limited", only that model is skipped for 20 seconds. If every
  model fails, the pre-written lines keep the round going.
- `gpt-oss` models "think" before answering, so they're sent `reasoning_effort: low`.
  Without it, they run out of tokens and return broken JSON.
- Free model lists change: Groq removed its Llama models and Gemini closed the 2.5 models to
  new keys. If a model disappears, run `scripts/try_models.py --list` and update `.env`.
