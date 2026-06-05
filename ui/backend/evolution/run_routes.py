"""Internal evolution evidence helpers used by /api/evolution-runs/*."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agent.common.paths import DEFAULT as DEFAULT_PATHS
from ui.backend.shared.helpers import (
    list_games_in_run,
    read_game_decisions,
    read_game_events,
    resolve_role_evolution_training_run_dir,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_battle_run_dir(runner, run_id: str, side: str) -> Path | None:
    """Find the battle directory for baseline or candidate."""
    evo_dir = DEFAULT_PATHS.evolution_dir / run_id / "battle" / side
    if not evo_dir.exists():
        return None
    # Find the run_* directory
    for child in sorted(evo_dir.iterdir(), reverse=True):
        if child.is_dir() and child.name.startswith("run_") and (child / "games").exists():
            return child
    return None


# ---------------------------------------------------------------------------
# Internal helpers — diff
# ---------------------------------------------------------------------------


def get_role_evolution_diff(
    run_id: str,
    runner: Any,
) -> dict[str, Any]:
    """Get the skill diffs produced by a run."""
    tracked = runner.get_run(run_id)
    if tracked is None:
        raise HTTPException(status_code=404, detail="run not found")
    # Try in-memory first
    if tracked.run is not None and tracked.run.diff is not None:
        return {
            "kind": "role_evolution_diff",
            "schema_version": 1,
            "run_id": run_id,
            "diffs": [d.to_dict() for d in tracked.run.diff],
        }
    # Fall back to disk
    evo_dir = DEFAULT_PATHS.evolution_dir / run_id
    diff_path = evo_dir / "diff.json"
    if diff_path.exists():
        try:
            return json.loads(diff_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logging.getLogger(__name__).warning("Corrupt diff.json in %s", evo_dir)
            return {
                "kind": "role_evolution_diff",
                "schema_version": 1,
                "run_id": run_id,
                "diffs": [],
            }
    return {
        "kind": "role_evolution_diff",
        "schema_version": 1,
        "run_id": run_id,
        "diffs": [],
    }


# ---------------------------------------------------------------------------
# Internal helpers — training games
# ---------------------------------------------------------------------------


def list_role_evolution_training_games(
    run_id: str,
    runner: Any,
) -> dict[str, Any]:
    """List training games produced by a role evolution run."""
    run_dir = resolve_role_evolution_training_run_dir(run_id, runner)
    if run_dir is None:
        if runner.get_run(run_id) is not None:
            return {"run_id": run_id, "games": []}
        raise HTTPException(status_code=404, detail="training run not found")
    return list_games_in_run(run_id, run_dir)


def get_role_evolution_training_game_events(
    run_id: str,
    game_id: str,
    runner: Any,
) -> dict[str, Any]:
    run_dir = resolve_role_evolution_training_run_dir(run_id, runner)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="training run not found")
    events = read_game_events(run_dir / "games" / game_id)
    if events is None:
        raise HTTPException(status_code=404, detail="game events not found")
    return {
        "run_id": run_id,
        "game_id": game_id,
        "events": events,
    }


def get_role_evolution_training_game_decisions(
    run_id: str,
    game_id: str,
    runner: Any,
) -> dict[str, Any]:
    run_dir = resolve_role_evolution_training_run_dir(run_id, runner)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="training run not found")
    decisions = read_game_decisions(run_dir / "games" / game_id)
    if decisions is None:
        raise HTTPException(status_code=404, detail="game decisions not found")
    return {
        "run_id": run_id,
        "game_id": game_id,
        "decisions": decisions,
    }


def get_role_evolution_training_game_archive(
    run_id: str,
    game_id: str,
    runner: Any,
) -> dict[str, Any]:
    run_dir = resolve_role_evolution_training_run_dir(run_id, runner)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="training run not found")
    archive_path = run_dir / "games" / game_id / "archive.json"
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="game archive not found")
    try:
        return json.loads(archive_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logging.getLogger(__name__).warning("Corrupt archive.json in %s", archive_path.parent)
        raise HTTPException(status_code=404, detail="game archive is corrupt")


# ---------------------------------------------------------------------------
# Internal helpers — battle games
# ---------------------------------------------------------------------------


def list_battle_games(
    run_id: str,
    side: str,
    runner: Any,
) -> dict[str, Any]:
    """List battle games for baseline or candidate side."""
    if side not in ("baseline", "candidate"):
        raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
    run_dir = _resolve_battle_run_dir(runner, run_id, side)
    if run_dir is None:
        return {"run_id": run_id, "side": side, "games": []}
    result = list_games_in_run(run_id, run_dir)
    result["side"] = side
    return result


def get_battle_game_events(
    run_id: str,
    side: str,
    game_id: str,
    runner: Any,
) -> dict[str, Any]:
    if side not in ("baseline", "candidate"):
        raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
    run_dir = _resolve_battle_run_dir(runner, run_id, side)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="battle run not found")
    events = read_game_events(run_dir / "games" / game_id)
    if events is None:
        raise HTTPException(status_code=404, detail="game events not found")
    return {"run_id": run_id, "game_id": game_id, "side": side, "events": events}


def get_battle_game_decisions(
    run_id: str,
    side: str,
    game_id: str,
    runner: Any,
) -> dict[str, Any]:
    if side not in ("baseline", "candidate"):
        raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
    run_dir = _resolve_battle_run_dir(runner, run_id, side)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="battle run not found")
    decisions = read_game_decisions(run_dir / "games" / game_id)
    if decisions is None:
        raise HTTPException(status_code=404, detail="game decisions not found")
    return {
        "run_id": run_id,
        "game_id": game_id,
        "side": side,
        "decisions": decisions,
    }


def get_battle_game_archive(
    run_id: str,
    side: str,
    game_id: str,
    runner: Any,
) -> dict[str, Any]:
    if side not in ("baseline", "candidate"):
        raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
    run_dir = _resolve_battle_run_dir(runner, run_id, side)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="battle run not found")
    archive_path = run_dir / "games" / game_id / "archive.json"
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="game archive not found")
    try:
        return json.loads(archive_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logging.getLogger(__name__).warning("Corrupt archive.json in %s", archive_path.parent)
        raise HTTPException(status_code=404, detail="game archive is corrupt")
