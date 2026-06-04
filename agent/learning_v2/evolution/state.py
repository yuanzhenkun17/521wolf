"""Run state persistence for role evolution."""

from __future__ import annotations

import json
from pathlib import Path

from agent.common.paths import PathConfig, DEFAULT as DEFAULT_PATHS
from agent.learning_v2.evolution.models import EvolutionRun, EvolutionStatus
from agent.common import beijing_now_iso, write_json

TERMINAL_STATUSES: set[str] = {
    EvolutionStatus.PROMOTED,
    EvolutionStatus.REJECTED,
    EvolutionStatus.FAILED,
}


def run_dir(paths: PathConfig, run_id: str) -> Path:
    """Return the on-disk directory for an evolution run."""
    return paths.evolution_dir / run_id


def state_path(paths: PathConfig, run_id: str) -> Path:
    """Return the persisted state.json path for an evolution run."""
    return run_dir(paths, run_id) / "state.json"


def save_run_state(run: EvolutionRun, paths: PathConfig = DEFAULT_PATHS) -> None:
    """Persist the current run state."""
    state = {
        "run_id": run.run_id,
        "role": run.role,
        "parent_hash": run.parent_hash,
        "candidate_hash": run.candidate_hash,
        "status": run.status,
        "updated_at": beijing_now_iso(),
        "errors": list(run.errors),
        "failed_stage": run.status if run.status == EvolutionStatus.FAILED else None,
        "training_games": run.training_games,
        "battle_games": run.battle_games,
        "training_run_id": run.training_run_id,
        "training_output_dir": run.training_output_dir,
        "baseline_config": run.baseline_config.to_dict() if run.baseline_config is not None else None,
    }
    write_json(state_path(paths, run.run_id), state)


def load_run_state(paths: PathConfig, run_id: str) -> dict | None:
    """Load persisted run state, returning None if it does not exist."""
    p = state_path(paths, run_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def training_run_dir(run: EvolutionRun, paths: PathConfig = DEFAULT_PATHS) -> Path | None:
    """Return the nested selfplay training run directory, if known."""
    if run.training_output_dir:
        p = Path(run.training_output_dir)
        if p.exists():
            return p
    if run.training_run_id:
        p = run_dir(paths, run.run_id) / run.training_run_id
        if p.exists():
            return p
    return None