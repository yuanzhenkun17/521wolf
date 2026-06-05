"""Routes for /api/games/* — game management (start, list, detail, SSE, archive, review, human actions)."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ui.backend.shared.helpers import (
    get_game_manager,
    get_version_registry,
    resolve_allowed_skill_dir,
)

router = APIRouter(prefix="/api/games", tags=["games"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class StartGameRequest(BaseModel):
    seed: int | None = None
    max_days: int = Field(default=20, ge=1, le=100)
    enable_sheriff: bool = True
    skill_dir: str | None = None
    player_count: int = Field(default=12, ge=12, le=12)
    role_versions: dict[str, str] | None = None  # {role: version_id}
    human_player_id: int | None = Field(default=None, ge=1, le=12)


class HumanActionSubmitRequest(BaseModel):
    action_type: str
    target: int | None = None
    choice: str | None = None
    text: str = ""


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("")
def list_games(
    manager: Annotated[Any, Depends(get_game_manager)],
) -> dict[str, Any]:
    return {"games": manager.list_games()}


@router.post("", status_code=201)
async def start_game(
    manager: Annotated[Any, Depends(get_game_manager)],
    version_registry: Annotated[Any, Depends(get_version_registry)],
    request: StartGameRequest | None = None,
) -> dict[str, Any]:
    try:
        role_skill_dirs = None
        if request is not None and request.role_versions:
            role_skill_dirs = {}
            for role, version_id in request.role_versions.items():
                role_skill_dirs[role] = version_registry.get_skill_dir(role, version_id)
        game = await manager.start_game(
            seed=request.seed if request is not None else None,
            max_days=request.max_days if request is not None else 20,
            enable_sheriff=request.enable_sheriff if request is not None else True,
            skill_dir=resolve_allowed_skill_dir(request.skill_dir) if request is not None else None,
            player_count=request.player_count if request is not None else 12,
            role_skill_dirs=role_skill_dirs,
            human_player_id=request.human_player_id if request is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return manager.snapshot(game, include_events=False)


@router.get("/{game_id}")
def get_game(
    game_id: str,
    manager: Annotated[Any, Depends(get_game_manager)],
) -> dict[str, Any]:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    return manager.snapshot(game)


@router.post("/{game_id}/stop")
async def stop_game(
    game_id: str,
    manager: Annotated[Any, Depends(get_game_manager)],
) -> dict[str, Any]:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    if game.task is not None and not game.task.done():
        game.task.cancel()
        try:
            await game.task
        except asyncio.CancelledError:
            pass
    game.status = "cancelled"
    return manager.snapshot(game, include_events=False)


@router.get("/{game_id}/human-action", response_model=None)
def get_human_action(
    game_id: str,
    manager: Annotated[Any, Depends(get_game_manager)],
) -> Any:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    pending = manager.pending_human_action(game_id)
    if pending is None:
        return Response(status_code=204)
    return pending


@router.post("/{game_id}/action", status_code=204)
def submit_human_action(
    game_id: str,
    request: HumanActionSubmitRequest,
    manager: Annotated[Any, Depends(get_game_manager)],
) -> Response:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    try:
        submitted = manager.submit_human_action(
            game_id,
            action_type=request.action_type,
            target=request.target,
            choice=request.choice,
            text=request.text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not submitted:
        raise HTTPException(status_code=409, detail="no pending human action")
    return Response(status_code=204)


@router.get("/{game_id}/events")
async def stream_game_events(
    game_id: str,
    manager: Annotated[Any, Depends(get_game_manager)],
) -> StreamingResponse:
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


@router.get("/{game_id}/archive")
def get_game_archive(
    game_id: str,
    manager: Annotated[Any, Depends(get_game_manager)],
) -> dict[str, Any]:
    """Read the full trace archive for a game (prompts, decisions, etc.)."""
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    archive = manager.read_archive(game_id)
    if archive is None:
        raise HTTPException(status_code=404, detail="archive not available")
    return archive


@router.get("/{game_id}/review")
def get_game_review(
    game_id: str,
    manager: Annotated[Any, Depends(get_game_manager)],
) -> dict[str, Any]:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    review = manager.build_review(game_id)
    if review is None:
        raise HTTPException(status_code=404, detail="review not available")
    return review
