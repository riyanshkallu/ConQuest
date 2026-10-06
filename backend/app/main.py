"""FastAPI app: the HTTP routes from api.md, plus the frontend as static files.

Run from backend/:  .venv/Scripts/python -m uvicorn app.main:app --reload
Then open http://127.0.0.1:8000 (game) or http://127.0.0.1:8000/docs (API docs).
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import game, schemas, store
from .ai import get_ai
from .config import BACKEND_DIR, get_settings

app = FastAPI(title="Outsmart API", description="See api.md in the repo for the full contract.")


# --- Errors in the api.md shape --------------------------------------------

def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(game.GameError)
async def game_error(_: Request, exc: game.GameError):
    return _error(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    return _error(400, "invalid_request", first.get("msg", "Invalid request."))


@app.exception_handler(Exception)
async def server_error(_: Request, exc: Exception):
    return _error(500, "server_error", "Something went wrong, try again.")


# --- Routes -------------------------------------------------------------------

@app.get("/api/health")
async def health():
    """Pinged by the keep-awake job so the free server doesn't fall asleep."""
    # Always 200 so Render doesn't restart the app over a database hiccup; the body says what's wrong.
    database = "ok" if store.database_ok() else "unreachable"
    return {"ok": database == "ok", "ai_provider": get_settings().ai_provider, "database": database}


@app.post("/api/player", response_model=schemas.PlayerResponse, status_code=201)
async def create_player(body: schemas.CreatePlayerRequest | None = None):
    player = game.create_player(body.display_name if body else None)
    return _player_out(player)


@app.patch("/api/player/{player_id}/settings", response_model=schemas.Settings)
async def update_settings(player_id: str, body: schemas.SettingsUpdate):
    player = game.require_player(player_id)
    if body.hints is not None:
        player.hints = body.hints
    if body.save_conversations is not None:
        player.save_conversations = body.save_conversations
    store.save_player(player)
    return schemas.Settings(hints=player.hints, save_conversations=player.save_conversations)


@app.post("/api/player/{player_id}/reset", response_model=schemas.RadarResponse)
async def reset_player(player_id: str):
    player = game.require_player(player_id)
    player.reset()
    store.save_player(player)
    return game.radar(player)


@app.get("/api/player/{player_id}/radar", response_model=schemas.RadarResponse)
async def get_radar(player_id: str):
    return game.radar(game.require_player(player_id))


@app.get("/api/scenarios", response_model=schemas.ScenarioListResponse)
async def list_scenarios(player_id: str):
    return game.list_scenarios(game.require_player(player_id))


@app.post("/api/round/start", response_model=schemas.StartRoundResponse, status_code=201)
async def start_round(body: schemas.StartRoundRequest):
    return await game.start_round(game.require_player(body.player_id), body.scenario_id, get_ai(), body.focus)


@app.post("/api/round/{round_id}/message", response_model=schemas.TurnResponse)
async def send_message(round_id: str, body: schemas.SendMessageRequest):
    rnd = game.require_round(round_id)
    async with _one_at_a_time(rnd):
        return await game.send_message(rnd, body.text, get_ai())


@app.post("/api/round/{round_id}/action", response_model=schemas.ActionResponse)
async def do_action(round_id: str, body: schemas.ActionRequest):
    rnd = game.require_round(round_id)
    async with _one_at_a_time(rnd):
        return await game.do_action(rnd, body.action, body.link, get_ai())


@app.get("/api/round/{round_id}/result", response_model=schemas.ResultResponse)
async def get_result(round_id: str):
    return await game.get_result(game.require_round(round_id), get_ai())


def _one_at_a_time(rnd):
    """A double-tapped send gets 409 round_busy instead of playing two turns."""
    if rnd.lock.locked():
        raise game.GameError(409, "round_busy", "Still working on your last message.")
    return rnd.lock


def _player_out(player) -> schemas.PlayerResponse:
    return schemas.PlayerResponse(
        player_id=player.id, display_name=player.display_name,
        settings=schemas.Settings(hints=player.hints, save_conversations=player.save_conversations))


@app.get("/play", include_in_schema=False)
async def test_console():
    """Backend test page for playing rounds before the real frontend exists. Not the game UI."""
    return FileResponse(BACKEND_DIR / "devtools" / "play.html")


# --- Frontend -----------------------------------------------------------------
# Mounted last so /api/* routes win. One server, one link for judges, no CORS setup.
_frontend = BACKEND_DIR.parent / "frontend"
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
