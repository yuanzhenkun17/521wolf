"""Role evolution pipeline — self-evolution state machine.

Orchestrates the full evolution lifecycle for a single role:
  queued -> training -> consolidating -> applying -> battling -> reviewing
  -> promoted / rejected
Any running stage may transition to -> failed on exception.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.role_evolution.applier import apply_proposals
from agent.role_evolution.config import build_baseline_config, build_role_override_config
from agent.role_evolution.models import (
    EvolutionRun,
    EvolutionStatus,
    SkillConsolidation,
    SkillVersionConfig,
)
from agent.role_evolution.store import VersionStore
from agent.runtime.model import ModelAdapter

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class InvalidRunStateError(Exception):
    """Raised when an operation is attempted on a run in an invalid state."""


class BaselineChangedError(Exception):
    """Raised when the baseline hash changed since the run started."""


# ---------------------------------------------------------------------------
# JSON helper (atomic write via os.replace)
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict) -> None:
    """Atomically write JSON to *path* using a tmp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    content = json.dumps(data, ensure_ascii=False, indent=2)
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

# Terminal statuses that should NOT be overwritten on startup recovery.
_TERMINAL: set[str] = {EvolutionStatus.PROMOTED, EvolutionStatus.REJECTED, EvolutionStatus.FAILED}


def _run_dir(store: VersionStore, run_id: str) -> Path:
    """Return the on-disk directory for an evolution run."""
    return store.base_dir / "runs" / "evolution" / run_id


def _state_path(store: VersionStore, run_id: str) -> Path:
    return _run_dir(store, run_id) / "state.json"


def _save_state(run: EvolutionRun, store: VersionStore) -> None:
    """Persist the current run state to state.json."""
    path = _state_path(store, run.run_id)
    state = {
        "run_id": run.run_id,
        "role": run.role,
        "parent_hash": run.parent_hash,
        "candidate_hash": run.candidate_hash,
        "status": run.status,
        "updated_at": _now(),
        "error": run.errors[-1] if run.errors else None,
        "failed_stage": run.status if run.status == EvolutionStatus.FAILED else None,
        "training_games": run.training_games,
        "battle_games": run.battle_games,
    }
    _write_json(path, state)


def _load_state(store: VersionStore, run_id: str) -> dict | None:
    """Load state.json for a run, returning None if missing."""
    path = _state_path(store, run_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Scan / recovery
# ---------------------------------------------------------------------------


def scan_active_runs(store: VersionStore) -> list[dict]:
    """Scan all ``runs/evolution/*/state.json`` and return runs with non-terminal status."""
    active: list[dict] = []
    evo_root = store.base_dir / "runs" / "evolution"
    if not evo_root.exists():
        return active
    for child in sorted(evo_root.iterdir()):
        state_file = child / "state.json"
        if not state_file.is_file():
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        status = state.get("status", "")
        if status not in _TERMINAL:
            active.append(state)
    return active


def recover_interrupted_runs(store: VersionStore) -> list[dict]:
    """On startup, mark any non-terminal runs as failed (reason=interrupted).

    Returns the list of runs that were marked failed.
    """
    interrupted: list[dict] = []
    for state in scan_active_runs(store):
        original_status = state.get("status", "unknown")
        state["status"] = EvolutionStatus.FAILED
        state["error"] = "interrupted"
        state["failed_stage"] = original_status
        state["updated_at"] = _now()
        evo_root = store.base_dir / "runs" / "evolution"
        state_file = evo_root / state["run_id"] / "state.json"
        _write_json(state_file, state)
        interrupted.append(state)
        _log.warning("Recovered interrupted run %s (role=%s)", state["run_id"], state.get("role"))
    return interrupted


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def run_evolution(
    store: VersionStore,
    role: str,
    training_games: int = 20,
    battle_games: int = 10,
    model_adapter: ModelAdapter | None = None,
    on_progress: Callable[[str, dict], None] | None = None,
    selfplay_runner: Callable | None = None,
    consolidator: Callable | None = None,
    applier: Callable | None = None,
    battle_runner: Callable | None = None,
) -> EvolutionRun:
    """Run the full evolution pipeline for *role*.

    Returns the :class:`EvolutionRun` in its terminal or reviewing state.
    On failure the run is persisted with ``status=failed`` and re-raised.
    """
    # Lazy defaults — avoid import cycles at module level
    if selfplay_runner is None:
        from agent.evaluation.selfplay import run_selfplay as _default_selfplay
        selfplay_runner = _default_selfplay
    if consolidator is None:
        from agent.cognition.long_term_consolidator import consolidate_for_role as _default_consolidator
        consolidator = _default_consolidator
    if applier is None:
        applier = apply_proposals
    if battle_runner is None:
        battle_runner = _run_battle

    # Resolve parent hash (current baseline)
    baseline = store.get_baseline(role)
    parent_hash = baseline.hash

    run_id = f"evo_{uuid.uuid4().hex[:12]}"
    rd = _run_dir(store, run_id)
    rd.mkdir(parents=True, exist_ok=True)

    run = EvolutionRun(
        run_id=run_id,
        role=role,
        parent_hash=parent_hash,
        status=EvolutionStatus.QUEUED,
        training_games=training_games,
        battle_games=battle_games,
    )
    _save_state(run, store)

    try:
        # ── Stage 1: Training ──────────────────────────────────────────
        run = await _stage_training(
            run, store, training_games, model_adapter,
            selfplay_runner, on_progress,
        )

        # ── Stage 2: Consolidating ─────────────────────────────────────
        run = await _stage_consolidating(
            run, store, model_adapter, consolidator, on_progress,
        )

        # ── Stage 3: Applying ──────────────────────────────────────────
        run = await _stage_applying(
            run, store, model_adapter, applier,
        )

        # ── Stage 4: Battling ──────────────────────────────────────────
        run = await _stage_battling(
            run, store, battle_games, model_adapter,
            selfplay_runner, battle_runner, on_progress,
        )

        # ── Stage 5: Reviewing ─────────────────────────────────────────
        run.status = EvolutionStatus.REVIEWING
        _save_state(run, store)
        _notify(on_progress, "reviewing", {"run_id": run.run_id})

    except Exception as exc:
        _log.exception("Evolution run %s failed at stage %s", run.run_id, run.status)
        run.status = EvolutionStatus.FAILED
        run.errors.append(str(exc))
        _save_state(run, store)
        raise

    return run


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------


async def _stage_training(
    run: EvolutionRun,
    store: VersionStore,
    training_games: int,
    model_adapter: ModelAdapter | None,
    selfplay_runner: Callable,
    on_progress: Callable | None,
) -> EvolutionRun:
    """Stage 1: Run selfplay training games with mid-memory enabled."""
    run.status = EvolutionStatus.TRAINING
    _save_state(run, store)
    _notify(on_progress, "training", {"run_id": run.run_id, "games": training_games})

    from agent.evaluation.selfplay import SelfPlayConfig

    run_dir = _run_dir(store, run.run_id)

    # Resolve baseline skill directory for the target role
    baseline_version = store.get_baseline(run.role)
    skill_dir = store.get_skill_dir(run.role, baseline_version.hash)

    config = SelfPlayConfig(
        games=training_games,
        output_dir=run_dir,
        enable_mid_memory=True,
        enable_long_term_consolidation=False,  # we consolidate manually in stage 2
        skill_dir=skill_dir,
    )

    def _on_game(idx: int, result: Any) -> None:
        _notify(on_progress, "training_game", {
            "run_id": run.run_id,
            "game_index": idx,
            "game_id": result.game_id if hasattr(result, "game_id") else str(idx),
        })

    await selfplay_runner(
        config,
        model=model_adapter,
        on_game_complete=_on_game,
    )
    return run


async def _stage_consolidating(
    run: EvolutionRun,
    store: VersionStore,
    model_adapter: ModelAdapter | None,
    consolidator: Callable,
    on_progress: Callable | None = None,
) -> EvolutionRun:
    """Stage 2: Consolidate mid-memory into skill proposals."""
    run.status = EvolutionStatus.CONSOLIDATING
    _save_state(run, store)
    _notify(on_progress, "consolidating", {"run_id": run.run_id})

    run_dir = _run_dir(store, run.run_id)

    consolidation: SkillConsolidation = await consolidator(
        run_dir, run.role, model_adapter,
        run_id=run.run_id,
        parent_hash=run.parent_hash,
    )
    run.proposals = consolidation
    _save_state(run, store)
    return run


async def _stage_applying(
    run: EvolutionRun,
    store: VersionStore,
    model_adapter: ModelAdapter | None,
    applier: Callable,
) -> EvolutionRun:
    """Stage 3: Apply proposals to produce candidate skill set."""
    run.status = EvolutionStatus.APPLYING
    _save_state(run, store)

    if run.proposals is None or not run.proposals.proposals:
        _log.info("No proposals to apply — skipping apply stage")
        # Use parent hash as candidate (no change)
        run.candidate_hash = run.parent_hash
        run.diff = []
        _save_state(run, store)
        return run

    # Load current skills from the baseline version
    baseline_version = store.load_version(run.role, run.parent_hash)
    current_skills = baseline_version.skills

    new_skills, diffs = await applier(current_skills, run.proposals, model_adapter)

    # Save candidate version to store
    candidate_hash = await store.save_version(
        role=run.role,
        skills=new_skills,
        parent_hash=run.parent_hash,
        source="evolution",
        source_run_id=run.run_id,
        notes=[f"evolution run {run.run_id}"],
    )

    run.candidate_hash = candidate_hash
    run.diff = diffs

    # Persist diff.json alongside state
    diff_path = _run_dir(store, run.run_id) / "diff.json"
    _write_json(diff_path, {"diffs": [d.to_dict() for d in diffs]})

    _save_state(run, store)
    return run


async def _stage_battling(
    run: EvolutionRun,
    store: VersionStore,
    battle_games: int,
    model_adapter: ModelAdapter | None,
    selfplay_runner: Callable,
    battle_runner: Callable,
    on_progress: Callable | None,
) -> EvolutionRun:
    """Stage 4: Battle baseline vs candidate."""
    run.status = EvolutionStatus.BATTLING
    _save_state(run, store)
    _notify(on_progress, "battling", {"run_id": run.run_id, "games": battle_games})

    if run.candidate_hash == run.parent_hash:
        _log.info("Candidate equals parent — skipping battle")
        run.battle_result = {"skipped": True, "reason": "no_changes"}
        _save_state(run, store)
        return run

    battle_result = await battle_runner(
        store, run.role, run.candidate_hash, battle_games,
        model_adapter, selfplay_runner, on_progress,
    )
    run.battle_result = battle_result

    # Persist battle summary
    battle_path = _run_dir(store, run.run_id) / "battle_summary.json"
    _write_json(battle_path, battle_result)

    _save_state(run, store)
    return run


# ---------------------------------------------------------------------------
# Battle implementation
# ---------------------------------------------------------------------------


async def _run_battle(
    store: VersionStore,
    role: str,
    candidate_hash: str,
    battle_games: int,
    model_adapter: ModelAdapter | None,
    selfplay_runner: Callable,
    on_progress: Callable | None,
) -> dict[str, Any]:
    """Run baseline vs candidate battle.

    Two configs (baseline vs candidate) are each run with the same seed range.
    Per-role metrics are aggregated and returned as a battle summary.
    """
    import shutil

    from agent.evaluation.selfplay import SelfPlayConfig

    seed_start = 10_000  # high seed to avoid collision with training

    svc_baseline = build_baseline_config(store)
    svc_candidate = build_role_override_config(store, role, candidate_hash)

    # Build composite skill directories for each side
    skill_dir_a = _build_composite_skill_dir(store, svc_baseline)
    skill_dir_b = _build_composite_skill_dir(store, svc_candidate)

    results_a: list[Any] = []
    results_b: list[Any] = []

    try:
        def _on_game_a(idx: int, result: Any) -> None:
            results_a.append(result)
            _notify(on_progress, "battle_game", {
                "side": "baseline",
                "game_index": idx,
            })

        def _on_game_b(idx: int, result: Any) -> None:
            results_b.append(result)
            _notify(on_progress, "battle_game", {
                "side": "candidate",
                "game_index": idx,
            })

        # Run baseline side
        cfg_a = SelfPlayConfig(
            games=battle_games,
            seed_start=seed_start,
            enable_mid_memory=False,
            enable_long_term_consolidation=False,
            skill_dir=skill_dir_a,
        )
        await selfplay_runner(cfg_a, model=model_adapter, on_game_complete=_on_game_a)

        # Run candidate side
        cfg_b = SelfPlayConfig(
            games=battle_games,
            seed_start=seed_start,
            enable_mid_memory=False,
            enable_long_term_consolidation=False,
            skill_dir=skill_dir_b,
        )
        await selfplay_runner(cfg_b, model=model_adapter, on_game_complete=_on_game_b)
    finally:
        # Clean up temporary directories
        for d in (skill_dir_a, skill_dir_b):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

    # Aggregate per-role metrics
    summary: dict[str, Any] = {
        "role": role,
        "candidate_hash": candidate_hash,
        "battle_games": battle_games,
        "baseline": _aggregate_metrics(results_a),
        "candidate": _aggregate_metrics(results_b),
    }
    return summary


def _build_composite_skill_dir(store: VersionStore, config: SkillVersionConfig) -> Path:
    """Create a temporary directory with skills assembled from a version config.

    Layout: ``<tmpdir>/<role>/*.md`` — one subdirectory per role, with skill
    files copied from the version store.
    """
    import shutil
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="evo_skills_"))
    for r, h in config.role_versions.items():
        try:
            src = store.get_skill_dir(r, h)
        except FileNotFoundError:
            _log.warning("Missing skill dir for %s/%s, skipping", r, h)
            continue
        dst = tmpdir / r
        shutil.copytree(src, dst)
    return tmpdir


def _aggregate_metrics(results: list[Any]) -> dict[str, Any]:
    """Aggregate per-game results into a summary dict."""
    if not results:
        return {"games": 0}

    valid = [r for r in results if not getattr(r, "error", None)]
    n = len(results)

    def _avg(attr: str, default: float = 0.0) -> float:
        vals = [getattr(r, attr, default) for r in valid]
        return sum(vals) / len(vals) if vals else 0.0

    return {
        "games": n,
        "errors": n - len(valid),
        "avg_review_score": _avg("review_score", 0.0),
        "avg_role_weighted_score": _avg("role_weighted_score", 0.0),
        "avg_speech_score": _avg("avg_speech_score", 0.0),
        "avg_vote_score": _avg("avg_vote_score", 0.0),
        "avg_skill_score": _avg("avg_skill_score", 0.0),
        "avg_information_score": _avg("information_score", 0.0),
        "avg_cooperation_score": _avg("cooperation_score", 0.0),
        "avg_confidence": _avg("avg_confidence", 0.0),
        "fallback_rate": _avg("fallback_count", 0.0),
        "vote_accuracy": _avg("vote_accuracy", 0.0),
        "skill_accuracy": _avg("skill_accuracy", 0.0),
    }


# ---------------------------------------------------------------------------
# Promote / reject
# ---------------------------------------------------------------------------


async def promote(run: EvolutionRun, store: VersionStore) -> None:
    """Promote a reviewing run's candidate to baseline.

    Idempotent: already promoted -> return.
    Raises InvalidRunStateError on terminal conflict or wrong state.
    Raises BaselineChangedError if baseline drifted.
    """
    # Idempotent
    if run.status == EvolutionStatus.PROMOTED:
        return

    # Terminal conflict
    if run.status in (EvolutionStatus.REJECTED, EvolutionStatus.FAILED):
        raise InvalidRunStateError(
            f"Cannot promote run {run.run_id}: status is {run.status}"
        )

    # Must be reviewing
    if run.status != EvolutionStatus.REVIEWING:
        raise InvalidRunStateError(
            f"Cannot promote run {run.run_id}: status is {run.status}, expected reviewing"
        )

    # Verify baseline hasn't changed
    history = store.get_history(run.role)
    current_baseline = history.baseline

    # Baseline already equals candidate -> just set promoted
    if current_baseline == run.candidate_hash:
        run.status = EvolutionStatus.PROMOTED
        _save_state(run, store)
        return

    # Baseline changed (not parent, not candidate)
    if current_baseline != run.parent_hash:
        raise BaselineChangedError(
            f"Baseline for {run.role} changed from {run.parent_hash} "
            f"to {current_baseline} since run started"
        )

    # CAS set_baseline
    success = await store.set_baseline(
        role=run.role,
        target_hash=run.candidate_hash,
        expected_current=run.parent_hash,
    )
    if not success:
        raise BaselineChangedError(
            f"CAS failed for {run.role}: expected {run.parent_hash}"
        )

    run.status = EvolutionStatus.PROMOTED
    _save_state(run, store)


async def reject(run: EvolutionRun, store: VersionStore) -> None:
    """Reject a reviewing run.

    Idempotent: already rejected -> return.
    Raises InvalidRunStateError on terminal conflict or wrong state.
    """
    # Idempotent
    if run.status == EvolutionStatus.REJECTED:
        return

    # Terminal conflict
    if run.status in (EvolutionStatus.PROMOTED, EvolutionStatus.FAILED):
        raise InvalidRunStateError(
            f"Cannot reject run {run.run_id}: status is {run.status}"
        )

    # Must be reviewing
    if run.status != EvolutionStatus.REVIEWING:
        raise InvalidRunStateError(
            f"Cannot reject run {run.run_id}: status is {run.status}, expected reviewing"
        )

    run.status = EvolutionStatus.REJECTED
    _save_state(run, store)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _notify(callback: Callable | None, stage: str, data: dict) -> None:
    """Safely invoke the on_progress callback."""
    if callback is None:
        return
    try:
        callback(stage, data)
    except Exception:
        _log.debug("on_progress callback raised for stage %s", stage, exc_info=True)
