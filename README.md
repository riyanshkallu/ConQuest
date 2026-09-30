# Scam-Shield: Can You Outsmart the Scammer?

A web game where you chat with an AI that is trying to scam you, or with a contact who is
actually real, and have to decide who to trust. Built for the Congressional App Challenge 2026.

## Repo layout

| Path | Owner | What's there |
| --- | --- | --- |
| `api.md` | both | The JSON contract between frontend and backend. Change only when both agree. |
| `backend/` | backend | Python + FastAPI: game engine, AI roles, database, API |
| `frontend/` | frontend | HTML, CSS and plain JavaScript single-page app (no build step) |

## Everything runs on free tiers

| Piece | Service | Free-tier limits to know about |
| --- | --- | --- |
| AI (main) | Groq API | No card needed. Limits are per model, about 30 requests/minute and 1,000+ per day |
| AI (backup) | Google Gemini API (AI Studio key) | No card needed. Flash models only, with daily request caps |
| Database | Supabase | Pauses after 7 days with no activity |
| Hosting | Render web service | Sleeps after 15 min idle (about 1 min to wake up), 750 hours/month |
| Keep-awake | GitHub Actions cron | Pings the app so judges don't hit a sleeping server |

Each chat turn uses 2 AI calls (analyzer + character), so one 10-turn round is about 20 calls.
When a provider hits its limit, the backend moves on to the next provider, then to
pre-written fallback lines, so the game never stops.

## Running the backend locally

See [backend/README.md](backend/README.md).
