from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.observability.stream import get_broadcaster

from ui.backend.game_runner import GameManager


class StartGameRequest(BaseModel):
    seed: int | None = None


manager = GameManager()
app = FastAPI(title="521wolf UI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/games")
def list_games() -> dict[str, Any]:
    return {"games": manager.list_games()}


@app.post("/api/games", status_code=201)
async def start_game(request: StartGameRequest | None = None) -> dict[str, Any]:
    try:
        game = await manager.start_game(seed=request.seed if request is not None else None)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return manager.snapshot(game, include_events=False)


@app.get("/api/games/{game_id}")
def get_game(game_id: str) -> dict[str, Any]:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    return manager.snapshot(game)


@app.get("/api/games/{game_id}/events")
async def stream_game_events(game_id: str) -> StreamingResponse:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")

    async def event_stream():
        queue = await manager.subscribe(game)
        try:
            while True:
                item = await queue.get()
                event_name = item["kind"]
                payload = json.dumps(item["payload"], ensure_ascii=False)
                yield f"event: {event_name}\ndata: {payload}\n\n"
                if event_name in {"done", "error"}:
                    break
        finally:
            manager.unsubscribe(game, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/games/{game_id}/archive")
def get_game_archive(game_id: str) -> dict[str, Any]:
    """Read the full trace archive for a game (ToT candidates, prompts, etc.)."""
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    archive = manager.read_archive(game_id)
    if archive is None:
        raise HTTPException(status_code=404, detail="archive not available")
    return archive


@app.get("/api/games/{game_id}/review")
def get_game_review(game_id: str) -> dict[str, Any]:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    review = manager.build_review(game_id)
    if review is None:
        raise HTTPException(status_code=404, detail="review not available")
    return review


@app.websocket("/ws/debug")
async def debug_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    bc = get_broadcaster()
    # Wait up to 30s for a game to start
    waited = 0.0
    while bc is None and waited < 30.0:
        await asyncio.sleep(0.5)
        waited += 0.5
        bc = get_broadcaster()
    if bc is None:
        await websocket.close(code=1011, reason="no active game")
        return
    q = bc.subscribe()
    try:
        while True:
            data = await q.get()
            await websocket.send_json(data)
    except WebSocketDisconnect:
        pass
    finally:
        bc.unsubscribe(q)


# ── Leaderboard ───────────────────────────────────────────────────────────────


_LEADERBOARD_PATHS = [
    Path("logs/version_battle/leaderboard.json"),
    Path("data/version_battle/leaderboard.json"),
    Path("leaderboard.json"),
]


@app.get("/api/leaderboards")
def list_leaderboards() -> dict[str, Any]:
    """Read leaderboard from known output paths."""
    for path in _LEADERBOARD_PATHS:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, list):
                return {"entries": data, "source": str(path)}
            if isinstance(data, dict) and "entries" in data:
                return {**data, "source": str(path)}
    return {"entries": [], "source": None}

