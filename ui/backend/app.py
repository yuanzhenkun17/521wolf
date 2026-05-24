from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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

