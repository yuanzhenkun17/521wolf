"""Canonical routes for /api/evolution-runs/*."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ui.backend.shared.helpers import (
    apply_batch_evolution_action,
    apply_role_evolution_action,
    get_role_batch_evolution_runner,
    get_role_evolution_runner,
    require_battle_side,
)

# Import route handler functions from sibling modules for delegation
from ui.backend.evolution.run_routes import (
    get_battle_game_archive,
    get_battle_game_decisions,
    get_battle_game_events,
    get_role_evolution_diff,
    get_role_evolution_training_game_archive,
    get_role_evolution_training_game_decisions,
    get_role_evolution_training_game_events,
    list_battle_games,
    list_role_evolution_training_games,
)

router = APIRouter(prefix="/api/evolution-runs", tags=["evolution-facade"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class EvolutionRunsStartRequest(BaseModel):
    roles: list[str] = Field(min_length=1)
    training_games: int = Field(default=20, ge=1, le=100)
    battle_games: int = Field(default=10, ge=1, le=100)
    role_concurrency: int | None = Field(default=None, ge=1, le=20)
    game_concurrency: int = Field(default=1, ge=1, le=20)
    llm_concurrency: int = Field(default=5, ge=1, le=100)
    llm_rpm: int = Field(default=60, ge=1, le=600)


class EvolutionRunActionRequest(BaseModel):
    action: str


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("")
def list_evolution_runs(
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
    batch_runner: Annotated[Any, Depends(get_role_batch_evolution_runner)],
) -> dict[str, Any]:
    return {
        "kind": "evolution_runs",
        "schema_version": 1,
        "runs": runner.list_runs(),
        "batches": batch_runner.list_batches(),
    }


@router.post("", status_code=201)
async def start_evolution_run(
    request: EvolutionRunsStartRequest,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
    batch_runner: Annotated[Any, Depends(get_role_batch_evolution_runner)],
) -> dict[str, Any]:
    if len(request.roles) == 1 and request.role_concurrency is None:
        role = request.roles[0]
        registry = getattr(runner, "registry", None)
        if registry is None or registry.get_baseline(role) is None:
            raise HTTPException(
                status_code=404,
                detail=f"role '{role}' has no baseline version",
            )
        tracked = await runner.start_evolution(
            role=role,
            training_games=request.training_games,
            battle_games=request.battle_games,
            game_concurrency=request.game_concurrency,
            llm_concurrency=request.llm_concurrency,
            llm_rpm=request.llm_rpm,
        )
        return tracked.snapshot()

    missing: list[str] = []
    registry = getattr(runner, "registry", None)
    for role in request.roles:
        if registry is None or registry.get_baseline(role) is None:
            missing.append(role)
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"roles have no baseline version: {', '.join(missing)}",
        )
    try:
        tracked = await batch_runner.start_batch(
            roles=request.roles,
            training_games=request.training_games,
            battle_games=request.battle_games,
            role_concurrency=request.role_concurrency or 2,
            game_concurrency=request.game_concurrency,
            llm_concurrency=request.llm_concurrency,
            llm_rpm=request.llm_rpm,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return tracked.snapshot()


@router.get("/{run_id}")
def get_evolution_run(
    run_id: str,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
    batch_runner: Annotated[Any, Depends(get_role_batch_evolution_runner)],
) -> dict[str, Any]:
    batch = batch_runner.get_batch(run_id)
    if batch is not None:
        return batch.snapshot()
    tracked = runner.get_run(run_id)
    if tracked is not None:
        return tracked.snapshot()
    raise HTTPException(status_code=404, detail="evolution run not found")


@router.post("/{run_id}/actions")
async def evolution_run_action(
    run_id: str,
    request: EvolutionRunActionRequest,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
    batch_runner: Annotated[Any, Depends(get_role_batch_evolution_runner)],
) -> dict[str, Any]:
    action = request.action
    batch = batch_runner.get_batch(run_id)
    if batch is not None:
        return await apply_batch_evolution_action(run_id, action, batch_runner)
    if runner.get_run(run_id) is not None:
        return await apply_role_evolution_action(run_id, action, runner)
    raise HTTPException(status_code=404, detail="evolution run not found")


@router.get("/{run_id}/events")
async def stream_evolution_run_events(
    run_id: str,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
    batch_runner: Annotated[Any, Depends(get_role_batch_evolution_runner)],
) -> StreamingResponse:
    if batch_runner.get_batch(run_id) is not None:
        async def batch_event_stream():
            async for chunk in batch_runner.sse_events(run_id):
                yield chunk

        return StreamingResponse(batch_event_stream(), media_type="text/event-stream")

    if runner.get_run(run_id) is not None:
        async def role_event_stream():
            async for chunk in runner.sse_events(run_id):
                yield chunk

        return StreamingResponse(role_event_stream(), media_type="text/event-stream")

    raise HTTPException(status_code=404, detail="evolution run not found")


@router.get("/{run_id}/diff")
def get_evolution_run_diff(
    run_id: str,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
) -> dict[str, Any]:
    return get_role_evolution_diff(run_id, runner)


@router.get("/{run_id}/games")
def list_evolution_run_games(
    run_id: str,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
    phase: str = "training",
    side: str | None = None,
) -> dict[str, Any]:
    if phase == "training":
        return list_role_evolution_training_games(run_id, runner)
    if phase == "battle":
        return list_battle_games(run_id, require_battle_side(side), runner)
    raise HTTPException(status_code=400, detail="phase must be 'training' or 'battle'")


@router.get("/{run_id}/games/{game_id}/events")
def get_evolution_run_game_events(
    run_id: str,
    game_id: str,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
    phase: str = "training",
    side: str | None = None,
) -> dict[str, Any]:
    if phase == "training":
        return get_role_evolution_training_game_events(run_id, game_id, runner)
    if phase == "battle":
        return get_battle_game_events(run_id, require_battle_side(side), game_id, runner)
    raise HTTPException(status_code=400, detail="phase must be 'training' or 'battle'")


@router.get("/{run_id}/games/{game_id}/decisions")
def get_evolution_run_game_decisions(
    run_id: str,
    game_id: str,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
    phase: str = "training",
    side: str | None = None,
) -> dict[str, Any]:
    if phase == "training":
        return get_role_evolution_training_game_decisions(run_id, game_id, runner)
    if phase == "battle":
        return get_battle_game_decisions(run_id, require_battle_side(side), game_id, runner)
    raise HTTPException(status_code=400, detail="phase must be 'training' or 'battle'")


@router.get("/{run_id}/games/{game_id}/archive")
def get_evolution_run_game_archive(
    run_id: str,
    game_id: str,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
    phase: str = "training",
    side: str | None = None,
) -> dict[str, Any]:
    if phase == "training":
        return get_role_evolution_training_game_archive(run_id, game_id, runner)
    if phase == "battle":
        return get_battle_game_archive(run_id, require_battle_side(side), game_id, runner)
    raise HTTPException(status_code=400, detail="phase must be 'training' or 'battle'")
