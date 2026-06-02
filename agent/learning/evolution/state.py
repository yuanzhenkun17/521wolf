"""Run state persistence for role evolution."""

from __future__ import annotations

import json
from pathlib import Path

from agent.learning.evolution.models import EvolutionRun, EvolutionStatus
from agent.learning.evolution.store import VersionStore
from agent.common import utc_now_iso, write_json

TERMINAL_STATUSES: set[str] = {
    EvolutionStatus.PROMOTED,
    EvolutionStatus.REJECTED,
    EvolutionStatus.FAILED,
}


def run_dir(store: VersionStore, run_id: str) -> Path:
    """Return the on-disk directory for an evolution run."""
    return store.base_dir / "runs" / "evolution" / run_id


def state_path(store: VersionStore, run_id: str) -> Path:
    """Return the persisted state.json path for an evolution run."""
    return run_dir(store, run_id) / "state.json"


def save_run_state(run: EvolutionRun, store: VersionStore) -> None:
    """Persist the current run state."""
    state = {
        "run_id": run.run_id,
        "role": run.role,
        "parent_hash": run.parent_hash,
        "candidate_hash": run.candidate_hash,
        "status": run.status,
        "updated_at": utc_now_iso(),
        "errors": list(run.errors),
        "failed_stage": run.status if run.status == EvolutionStatus.FAILED else None,
        "training_games": run.training_games,
        "battle_games": run.battle_games,
        "training_run_id": run.training_run_id,
        "training_output_dir": run.training_output_dir,
        "baseline_config": run.baseline_config.to_dict() if run.baseline_config is not None else None,
    }
    write_json(state_path(store, run.run_id), state)


def load_run_state(store: VersionStore, run_id: str) -> dict | None:
    """Load persisted run state, returning None if it does not exist."""
    path = state_path(store, run_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def training_run_dir(run: EvolutionRun, store: VersionStore) -> Path | None:
    """Return the nested selfplay training run directory, if known."""
    if run.training_output_dir:
        path = Path(run.training_output_dir)
        if path.exists():
            return path
    if run.training_run_id:
        path = run_dir(store, run.run_id) / run.training_run_id
        if path.exists():
            return path
    return None
