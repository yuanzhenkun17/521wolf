"""Routes for /api/selfplay/* — selfplay batch runs and game detail."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ui.backend.shared.helpers import (
    get_selfplay_manager,
    list_games_in_run,
    read_game_decisions,
    read_game_events,
    resolve_allowed_skill_dir,
)

router = APIRouter(prefix="/api/selfplay", tags=["selfplay"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SelfplayRequest(BaseModel):
    num_games: int = Field(default=10, ge=1, le=100)
    agent_version: str | None = None
    skill_dir: str | None = None
    max_days: int = Field(default=20, ge=1, le=100)
    enable_sheriff: bool = True
    enable_batch_dream: bool = False
    game_concurrency: int = Field(default=1, ge=1, le=20)
    llm_concurrency: int = Field(default=5, ge=1, le=100)
    llm_rpm: int = Field(default=60, ge=1, le=600)
    label: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_selfplay_run_dir(selfplay_manager, run_id: str) -> Path | None:
    """Find the output directory for a selfplay run."""
    run = selfplay_manager.get_run(run_id)
    if run is not None and run.artifact_run_id:
        path = Path("runs/selfplay") / run.artifact_run_id
        if path.exists():
            return path
    # Fallback to direct path
    path = Path("runs/selfplay") / run_id
    return path if path.exists() else None


# ---------------------------------------------------------------------------
# Route handlers — selfplay runs
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def start_selfplay(
    selfplay_manager: Annotated[Any, Depends(get_selfplay_manager)],
    request: SelfplayRequest | None = None,
) -> dict[str, Any]:
    """Start a batch selfplay run in the background. Returns the run_id."""
    if request is None:
        request = SelfplayRequest()
    agent_version = request.agent_version or "agent"
    skill_dir = resolve_allowed_skill_dir(request.skill_dir)
    run = await selfplay_manager.start_run(
        num_games=request.num_games,
        agent_version=agent_version,
        skill_dir=skill_dir,
        max_days=request.max_days,
        enable_sheriff=request.enable_sheriff,
        enable_batch_dream=request.enable_batch_dream,
        game_concurrency=request.game_concurrency,
        llm_concurrency=request.llm_concurrency,
        llm_rpm=request.llm_rpm,
        label=request.label,
    )
    return run.snapshot()


@router.get("")
def list_selfplays(
    selfplay_manager: Annotated[Any, Depends(get_selfplay_manager)],
) -> dict[str, Any]:
    """List all selfplay runs (active and completed)."""
    return {"runs": selfplay_manager.list_runs()}


@router.get("/{run_id}")
def get_selfplay(
    run_id: str,
    selfplay_manager: Annotated[Any, Depends(get_selfplay_manager)],
) -> dict[str, Any]:
    """Get status and progress of a specific selfplay run."""
    run = selfplay_manager.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


@router.post("/{run_id}/stop")
def stop_selfplay(
    run_id: str,
    selfplay_manager: Annotated[Any, Depends(get_selfplay_manager)],
) -> dict[str, Any]:
    """Stop a running selfplay task (can be resumed later)."""
    run = selfplay_manager.stop_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


@router.post("/{run_id}/resume")
def resume_selfplay(
    run_id: str,
    selfplay_manager: Annotated[Any, Depends(get_selfplay_manager)],
) -> dict[str, Any]:
    """Resume a paused or interrupted selfplay task."""
    run = selfplay_manager.resume_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


@router.post("/{run_id}/terminate")
def terminate_selfplay(
    run_id: str,
    selfplay_manager: Annotated[Any, Depends(get_selfplay_manager)],
) -> dict[str, Any]:
    """Permanently stop a selfplay run."""
    run = selfplay_manager.terminate_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


# ---------------------------------------------------------------------------
# Route handlers — selfplay game detail
# ---------------------------------------------------------------------------


@router.get("/{run_id}/games")
def list_selfplay_games(
    run_id: str,
    selfplay_manager: Annotated[Any, Depends(get_selfplay_manager)],
) -> dict[str, Any]:
    """List all games in a selfplay run with basic info."""
    run_dir = _resolve_selfplay_run_dir(selfplay_manager, run_id)
    if run_dir is None:
        if selfplay_manager.get_run(run_id) is not None:
            return {"run_id": run_id, "games": []}
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return list_games_in_run(run_id, run_dir)


@router.get("/{run_id}/games/{game_id}/events")
def get_selfplay_game_events(
    run_id: str,
    game_id: str,
    selfplay_manager: Annotated[Any, Depends(get_selfplay_manager)],
) -> dict[str, Any]:
    """Get all events for a specific game in a selfplay run."""
    run_dir = _resolve_selfplay_run_dir(selfplay_manager, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    events = read_game_events(run_dir / "games" / game_id)
    if events is None:
        raise HTTPException(status_code=404, detail="game events not found")
    return {"run_id": run_id, "game_id": game_id, "events": events}


@router.get("/{run_id}/games/{game_id}/decisions")
def get_selfplay_game_decisions(
    run_id: str,
    game_id: str,
    selfplay_manager: Annotated[Any, Depends(get_selfplay_manager)],
) -> dict[str, Any]:
    """Get agent decisions for a specific game."""
    run_dir = _resolve_selfplay_run_dir(selfplay_manager, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    decisions = read_game_decisions(run_dir / "games" / game_id)
    if decisions is None:
        raise HTTPException(status_code=404, detail="game decisions not found")
    return {"run_id": run_id, "game_id": game_id, "decisions": decisions}


@router.get("/{run_id}/games/{game_id}/archive")
def get_selfplay_game_archive(
    run_id: str,
    game_id: str,
    selfplay_manager: Annotated[Any, Depends(get_selfplay_manager)],
) -> dict[str, Any]:
    """Get full archive for a specific game."""
    run_dir = _resolve_selfplay_run_dir(selfplay_manager, run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    archive_path = run_dir / "games" / game_id / "archive.json"
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="game archive not found")
    try:
        return json.loads(archive_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logging.getLogger(__name__).warning("Corrupt archive.json in %s", archive_path.parent)
        raise HTTPException(status_code=404, detail="game archive is corrupt")
