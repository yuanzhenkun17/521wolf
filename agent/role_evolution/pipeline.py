"""Role evolution pipeline — self-evolution state machine.

Orchestrates the full evolution lifecycle for a single role:
  queued -> training -> consolidating -> applying -> battling -> reviewing
  -> promoted / rejected
Any running stage may transition to -> failed on exception.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.evaluation.metrics import _new_role_accum, finalize_role_metrics
from agent.role_evolution.applier import apply_proposals
from agent.role_evolution.config import build_baseline_config, build_role_override_from_config
from agent.role_evolution.models import (
    EvolutionRun,
    EvolutionStatus,
    SkillConsolidation,
    SkillVersionConfig,
)
from agent.role_evolution.store import VersionStore, _write_json
from agent.runtime.model import (
    AsyncRateLimiter,
    ModelAdapter,
    default_rate_limiter_from_env,
    limit_model_adapter,
    rate_limit_model_adapter,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class InvalidRunStateError(Exception):
    """Raised when an operation is attempted on a run in an invalid state."""


class BaselineChangedError(Exception):
    """Raised when the baseline hash changed since the run started."""


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------


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
        "errors": list(run.errors),
        "failed_stage": run.status if run.status == EvolutionStatus.FAILED else None,
        "training_games": run.training_games,
        "battle_games": run.battle_games,
        "training_run_id": run.training_run_id,
        "training_output_dir": run.training_output_dir,
        "baseline_config": run.baseline_config.to_dict() if run.baseline_config is not None else None,
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
    """On startup, mark runs that were actually interrupted as failed.

    Only marks runs as failed if they were in an active stage
    (training, consolidating, applying, battling), not if they
    were in reviewing or other terminal states.
    """
    _ACTIVE_STATUSES = {
        EvolutionStatus.QUEUED,
        EvolutionStatus.TRAINING,
        EvolutionStatus.CONSOLIDATING,
        EvolutionStatus.APPLYING,
        EvolutionStatus.BATTLING,
    }
    interrupted: list[dict] = []
    for state in scan_active_runs(store):
        status = state.get("status", "unknown")
        if status not in _ACTIVE_STATUSES:
            continue
        state["status"] = EvolutionStatus.FAILED
        state["error"] = "interrupted"
        state["failed_stage"] = status
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
    baseline_config: SkillVersionConfig | None = None,
    game_concurrency: int = 1,
    llm_semaphore: asyncio.Semaphore | None = None,
    llm_rate_limiter: AsyncRateLimiter | None = None,
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

    # Freeze the baseline config for the whole run.  This avoids a later
    # baseline change leaking into training or battle for the same candidate.
    baseline_config = baseline_config or build_baseline_config(store)
    try:
        parent_hash = baseline_config.role_versions[role]
    except KeyError as exc:
        raise KeyError(f"Role '{role}' not found in baseline config") from exc
    store.load_version(role, parent_hash)
    llm_rate_limiter = llm_rate_limiter or default_rate_limiter_from_env()
    limited_model = (
        limit_model_adapter(model_adapter, llm_semaphore)
        if model_adapter is not None else None
    )
    if limited_model is not None:
        limited_model = rate_limit_model_adapter(limited_model, llm_rate_limiter)

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
        baseline_config=baseline_config,
    )
    _save_state(run, store)

    try:
        # ── Stage 1: Training ──────────────────────────────────────────
        run = await _stage_training(
            run, store, training_games, limited_model, game_concurrency,
            llm_semaphore, llm_rate_limiter,
            selfplay_runner, on_progress,
        )

        # ── Stage 2: Consolidating ─────────────────────────────────────
        run = await _stage_consolidating(
            run, store, limited_model, consolidator, on_progress,
        )

        # ── Stage 3: Applying ──────────────────────────────────────────
        run = await _stage_applying(
            run, store, limited_model, applier,
        )

        # ── Stage 4: Battling ──────────────────────────────────────────
        run = await _stage_battling(
            run, store, battle_games, limited_model, game_concurrency,
            llm_semaphore, llm_rate_limiter,
            selfplay_runner, battle_runner, on_progress,
        )

        # ── Stage 5: Reviewing ─────────────────────────────────────────
        run.status = EvolutionStatus.REVIEWING
        _save_state(run, store)
        _notify(on_progress, "reviewing", {"run_id": run.run_id})

    except Exception as exc:
        failed_stage = run.status
        _log.exception("Evolution run %s failed at stage %s", run.run_id, failed_stage)
        run.status = EvolutionStatus.FAILED
        run.errors.append(str(exc))
        _save_state(run, store)
        state_path = _state_path(store, run.run_id)
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["failed_stage"] = failed_stage
            _write_json(state_path, state)
        except Exception:
            _log.debug("failed to patch failed_stage for %s", run.run_id, exc_info=True)
        raise

    return run


async def resume_evolution(
    store: VersionStore,
    run_id: str,
    model_adapter: ModelAdapter | None = None,
    game_concurrency: int = 1,
    llm_semaphore: asyncio.Semaphore | None = None,
    llm_rate_limiter: AsyncRateLimiter | None = None,
    on_progress: Callable[[str, dict], None] | None = None,
    selfplay_runner: Callable | None = None,
    consolidator: Callable | None = None,
    applier: Callable | None = None,
    battle_runner: Callable | None = None,
) -> EvolutionRun:
    """Resume a failed evolution run from the failed stage.

    Training and battle games that already completed are automatically
    skipped by the selfplay checkpoint mechanism.
    """
    state = _load_state(store, run_id)
    if state is None:
        raise KeyError(f"Run {run_id} not found on disk")

    failed_stage = state.get("failed_stage") or state.get("status")
    if failed_stage in _TERMINAL and failed_stage != EvolutionStatus.FAILED:
        raise InvalidRunStateError(f"Run {run_id} is in terminal state {failed_stage}")

    role = state["role"]
    training_games = state.get("training_games", 20)
    battle_games = state.get("battle_games", 10)

    # Reconstruct EvolutionRun from saved state
    from agent.role_evolution.models import SkillVersionConfig
    baseline_data = state.get("baseline_config")
    baseline_config = SkillVersionConfig.from_dict(baseline_data) if baseline_data else build_baseline_config(store)

    parent_hash = state.get("parent_hash", "")
    run = EvolutionRun(
        run_id=run_id,
        role=role,
        parent_hash=parent_hash,
        status=EvolutionStatus.TRAINING,
        training_games=training_games,
        battle_games=battle_games,
        baseline_config=baseline_config,
    )
    run.training_run_id = state.get("training_run_id")
    run.training_output_dir = state.get("training_output_dir")
    run.candidate_hash = state.get("candidate_hash")

    # Lazy defaults
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

    llm_rate_limiter = llm_rate_limiter or default_rate_limiter_from_env()
    limited_model = (
        limit_model_adapter(model_adapter, llm_semaphore)
        if model_adapter is not None else None
    )
    if limited_model is not None:
        limited_model = rate_limit_model_adapter(limited_model, llm_rate_limiter)

    # Determine which stages to skip
    stage_order = [
        EvolutionStatus.TRAINING,
        EvolutionStatus.CONSOLIDATING,
        EvolutionStatus.APPLYING,
        EvolutionStatus.BATTLING,
    ]
    try:
        resume_index = stage_order.index(failed_stage)
    except ValueError:
        resume_index = 0

    try:
        if resume_index <= 0:
            run = await _stage_training(
                run, store, training_games, limited_model, game_concurrency,
                llm_semaphore, llm_rate_limiter,
                selfplay_runner, on_progress,
            )

        if resume_index <= 1:
            run = await _stage_consolidating(
                run, store, limited_model, consolidator, on_progress,
            )

        if resume_index <= 2:
            run = await _stage_applying(
                run, store, limited_model, applier,
            )

        if resume_index <= 3:
            run = await _stage_battling(
                run, store, battle_games, limited_model, game_concurrency,
                llm_semaphore, llm_rate_limiter,
                selfplay_runner, battle_runner, on_progress,
            )

        run.status = EvolutionStatus.REVIEWING
        _save_state(run, store)
        _notify(on_progress, "reviewing", {"run_id": run.run_id})

    except Exception as exc:
        failed_stage_now = run.status
        _log.exception("Resumed evolution run %s failed at stage %s", run.run_id, failed_stage_now)
        run.status = EvolutionStatus.FAILED
        run.errors.append(str(exc))
        _save_state(run, store)
        state_path = _state_path(store, run.run_id)
        try:
            s = json.loads(state_path.read_text(encoding="utf-8"))
            s["failed_stage"] = failed_stage_now
            _write_json(state_path, s)
        except Exception:
            pass
        raise

    return run


async def rerun_from_consolidation(
    store: VersionStore,
    run_id: str,
    model_adapter: ModelAdapter | None = None,
    game_concurrency: int = 1,
    llm_semaphore: asyncio.Semaphore | None = None,
    llm_rate_limiter: AsyncRateLimiter | None = None,
    on_progress: Callable[[str, dict], None] | None = None,
    battle_runner: Callable | None = None,
) -> EvolutionRun:
    """Re-run from consolidation stage using existing training data.

    This reuses the mid-memory from a completed training run and
    re-runs consolidation -> applying -> battling with the updated prompt.
    """
    state = _load_state(store, run_id)
    if state is None:
        raise KeyError(f"Run {run_id} not found on disk")

    role = state["role"]
    training_games = state.get("training_games", 20)
    battle_games = state.get("battle_games", 10)

    from agent.role_evolution.models import SkillVersionConfig
    baseline_data = state.get("baseline_config")
    baseline_config = SkillVersionConfig.from_dict(baseline_data) if baseline_data else build_baseline_config(store)

    parent_hash = state.get("parent_hash", "")
    run = EvolutionRun(
        run_id=run_id,
        role=role,
        parent_hash=parent_hash,
        status=EvolutionStatus.CONSOLIDATING,
        training_games=training_games,
        battle_games=battle_games,
        baseline_config=baseline_config,
    )
    run.training_run_id = state.get("training_run_id")
    run.training_output_dir = state.get("training_output_dir")

    from agent.cognition.long_term_consolidator import consolidate_for_role as _default_consolidator
    if battle_runner is None:
        battle_runner = _run_battle

    llm_rate_limiter = llm_rate_limiter or default_rate_limiter_from_env()
    if model_adapter is None:
        from agent.runtime.factory import load_llm_client
        model_adapter = load_llm_client()
    limited_model = limit_model_adapter(model_adapter, llm_semaphore)
    limited_model = rate_limit_model_adapter(limited_model, llm_rate_limiter)

    from agent.evaluation.selfplay import run_selfplay as _default_selfplay

    try:
        run = await _stage_consolidating(
            run, store, limited_model, _default_consolidator, on_progress,
        )
        run = await _stage_applying(
            run, store, limited_model, apply_proposals,
        )
        run = await _stage_battling(
            run, store, battle_games, limited_model, game_concurrency,
            llm_semaphore, llm_rate_limiter,
            _default_selfplay, battle_runner, on_progress,
        )
        run.status = EvolutionStatus.REVIEWING
        _save_state(run, store)
        _notify(on_progress, "reviewing", {"run_id": run.run_id})
    except Exception as exc:
        _log.exception("Rerun from consolidation failed for %s", run_id)
        run.status = EvolutionStatus.FAILED
        run.errors.append(str(exc))
        _save_state(run, store)
        raise

    return run


async def _stage_training(
    run: EvolutionRun,
    store: VersionStore,
    training_games: int,
    model_adapter: ModelAdapter | None,
    game_concurrency: int,
    llm_semaphore: asyncio.Semaphore | None,
    llm_rate_limiter: AsyncRateLimiter | None,
    selfplay_runner: Callable,
    on_progress: Callable | None,
) -> EvolutionRun:
    """Stage 1: Run selfplay training games with mid-memory enabled."""
    run.status = EvolutionStatus.TRAINING
    _save_state(run, store)
    _notify(on_progress, "training", {"run_id": run.run_id, "games": training_games})

    from agent.evaluation.selfplay import SelfPlayConfig

    run_dir = _run_dir(store, run.run_id)

    baseline_config = run.baseline_config or build_baseline_config(store)
    skill_dir = _build_composite_skill_dir(store, baseline_config)

    config = SelfPlayConfig(
        games=training_games,
        output_dir=run_dir,
        enable_mid_memory=True,
        enable_long_term_consolidation=False,  # we consolidate manually in stage 2
        skill_dir=skill_dir,
        game_concurrency=game_concurrency,
    )

    completed = 0

    def _on_game(idx: int, result: Any) -> None:
        nonlocal completed
        completed += 1
        _notify(on_progress, "training_game", {
            "run_id": run.run_id,
            "game_index": idx,
            "completed": completed,
            "total": training_games,
            "game_id": result.game_id if hasattr(result, "game_id") else str(idx),
        })

    try:
        result = await _call_selfplay_runner(
            selfplay_runner,
            config,
            model=model_adapter,
            on_game_complete=_on_game,
            llm_semaphore=llm_semaphore,
            llm_rate_limiter=llm_rate_limiter,
        )
        training_run_id = str(getattr(result, "run_id", "") or "")
        if training_run_id:
            run.training_run_id = training_run_id
            run.training_output_dir = str(run_dir / training_run_id)
            _save_state(run, store)
            _notify(on_progress, "training_artifact", {
                "run_id": run.run_id,
                "training_run_id": run.training_run_id,
                "training_output_dir": run.training_output_dir,
            })
    finally:
        import shutil

        shutil.rmtree(skill_dir, ignore_errors=True)
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

    run_dir = _training_run_dir(run, store) or _run_dir(store, run.run_id)

    consolidation: SkillConsolidation = await consolidator(
        run_dir, run.role, model_adapter,
        run_id=run.run_id,
        parent_hash=run.parent_hash,
        skill_root=store.get_skill_dir(run.role, run.parent_hash),
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
    game_concurrency: int,
    llm_semaphore: asyncio.Semaphore | None,
    llm_rate_limiter: AsyncRateLimiter | None,
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

    battle_result = await _call_battle_runner(
        battle_runner,
        store, run.role, run.candidate_hash, battle_games,
        model_adapter, selfplay_runner, on_progress,
        baseline_config=run.baseline_config,
        game_concurrency=game_concurrency,
        llm_semaphore=llm_semaphore,
        llm_rate_limiter=llm_rate_limiter,
        output_dir=_run_dir(store, run.run_id) / "battle",
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
    *,
    baseline_config: SkillVersionConfig | None = None,
    game_concurrency: int = 1,
    llm_semaphore: asyncio.Semaphore | None = None,
    llm_rate_limiter: AsyncRateLimiter | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Run baseline vs candidate battle.

    Two configs (baseline vs candidate) are each run with the same seed range.
    Per-role metrics are aggregated and returned as a battle summary.
    """
    seed_start = 10_000  # high seed to avoid collision with training

    svc_baseline = baseline_config or build_baseline_config(store)
    svc_candidate = build_role_override_from_config(svc_baseline, role, candidate_hash)

    return await _run_config_battle(
        store=store,
        baseline_config=svc_baseline,
        candidate_config=svc_candidate,
        battle_games=battle_games,
        model_adapter=model_adapter,
        selfplay_runner=selfplay_runner,
        on_progress=on_progress,
        seed_start=seed_start,
        game_concurrency=game_concurrency,
        llm_semaphore=llm_semaphore,
        llm_rate_limiter=llm_rate_limiter,
        role=role,
        candidate_hash=candidate_hash,
        output_dir=output_dir,
    )


async def _run_config_battle(
    *,
    store: VersionStore,
    baseline_config: SkillVersionConfig,
    candidate_config: SkillVersionConfig,
    battle_games: int,
    model_adapter: ModelAdapter | None,
    selfplay_runner: Callable,
    on_progress: Callable | None,
    seed_start: int = 10_000,
    game_concurrency: int = 1,
    llm_semaphore: asyncio.Semaphore | None = None,
    llm_rate_limiter: AsyncRateLimiter | None = None,
    role: str | None = None,
    candidate_hash: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Run a fixed-seed battle between two full role-version configs."""
    import shutil

    from agent.evaluation.selfplay import SelfPlayConfig

    # Build composite skill directories for each side
    skill_dir_a = _build_composite_skill_dir(store, baseline_config)
    skill_dir_b = _build_composite_skill_dir(store, candidate_config)

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

        # Run both sides concurrently
        cfg_a = SelfPlayConfig(
            games=battle_games,
            seed_start=seed_start,
            output_dir=(output_dir / "baseline") if output_dir is not None else Path("runs/selfplay"),
            enable_mid_memory=False,
            enable_long_term_consolidation=False,
            skill_dir=skill_dir_a,
            game_concurrency=game_concurrency,
        )
        cfg_b = SelfPlayConfig(
            games=battle_games,
            seed_start=seed_start,
            output_dir=(output_dir / "candidate") if output_dir is not None else Path("runs/selfplay"),
            enable_mid_memory=False,
            enable_long_term_consolidation=False,
            skill_dir=skill_dir_b,
            game_concurrency=game_concurrency,
        )
        result_a, result_b = await asyncio.gather(
            _call_selfplay_runner(
                selfplay_runner,
                cfg_a,
                model=model_adapter,
                on_game_complete=_on_game_a,
                llm_semaphore=llm_semaphore,
                llm_rate_limiter=llm_rate_limiter,
            ),
            _call_selfplay_runner(
                selfplay_runner,
                cfg_b,
                model=model_adapter,
                on_game_complete=_on_game_b,
                llm_semaphore=llm_semaphore,
                llm_rate_limiter=llm_rate_limiter,
            ),
        )
    finally:
        # Clean up temporary directories
        for d in (skill_dir_a, skill_dir_b):
            shutil.rmtree(d, ignore_errors=True)

    # Aggregate per-role metrics
    summary: dict[str, Any] = {
        "role": role,
        "candidate_hash": candidate_hash,
        "battle_games": battle_games,
        "games_played": battle_games,
        "seeds": list(range(seed_start, seed_start + battle_games)),
        "baseline_config": baseline_config.to_dict(),
        "candidate_config": candidate_config.to_dict(),
        "baseline_selfplay": _selfplay_artifact_summary(result_a, cfg_a),
        "candidate_selfplay": _selfplay_artifact_summary(result_b, cfg_b),
        "baseline": _aggregate_metrics(results_a),
        "candidate": _aggregate_metrics(results_b),
    }
    summary["baseline_metrics"] = _metrics_for_leaderboard(summary["baseline"], role)
    summary["candidate_metrics"] = _metrics_for_leaderboard(summary["candidate"], role)
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


def _training_run_dir(run: EvolutionRun, store: VersionStore) -> Path | None:
    """Return the nested selfplay training run directory, if known."""
    if run.training_output_dir:
        path = Path(run.training_output_dir)
        if path.exists():
            return path
    if run.training_run_id:
        path = _run_dir(store, run.run_id) / run.training_run_id
        if path.exists():
            return path
    return None


def _selfplay_artifact_summary(result: Any, config: Any) -> dict[str, Any]:
    """Small serializable pointer to a nested selfplay run."""
    run_id = str(getattr(result, "run_id", "") or "")
    output_dir = Path(getattr(config, "output_dir", ""))
    games = getattr(result, "games", [])
    return {
        "run_id": run_id,
        "output_dir": str(output_dir / run_id) if run_id else str(output_dir),
        "games": [
            game.to_dict() if hasattr(game, "to_dict") else game
            for game in games
        ],
    }


def _aggregate_metrics(results: list[Any]) -> dict[str, Any]:
    """Aggregate per-game results into a summary dict."""
    if not results:
        return {"games": 0}

    valid = [r for r in results if not getattr(r, "error", None)]
    n = len(results)

    def _avg(attr: str, default: float = 0.0) -> float:
        vals = [getattr(r, attr, default) for r in valid]
        return sum(vals) / len(vals) if vals else 0.0

    total_decisions = sum(getattr(r, "decision_count", 0) for r in valid)
    total_fallbacks = sum(getattr(r, "fallback_count", 0) for r in valid)
    by_role = _aggregate_result_by_role(valid)

    return {
        "games": n,
        "errors": n - len(valid),
        "werewolf_win_rate": _win_rate(valid, "werewolf"),
        "villager_win_rate": _win_rate(valid, "villager"),
        "avg_review_score": _avg("review_score", 0.0),
        "avg_role_weighted_score": _avg("role_weighted_score", 0.0),
        "avg_speech_score": _avg("avg_speech_score", 0.0),
        "avg_vote_score": _avg("avg_vote_score", 0.0),
        "avg_skill_score": _avg("avg_skill_score", 0.0),
        "avg_information_score": _avg("information_score", 0.0),
        "avg_cooperation_score": _avg("cooperation_score", 0.0),
        "avg_confidence": _avg("avg_confidence", 0.0),
        "fallback_rate": total_fallbacks / total_decisions if total_decisions else 0.0,
        "vote_accuracy": _avg("vote_accuracy", 0.0),
        "skill_accuracy": _avg("skill_accuracy", 0.0),
        "by_role": by_role,
    }


def _metrics_for_leaderboard(
    metrics: dict[str, Any],
    role: str | None = None,
) -> dict[str, dict[str, float]]:
    """Expose coarse aggregate metrics in the shape expected by role leaderboard."""
    source = (
        metrics.get("by_role", {}).get(role, {})
        if role is not None and isinstance(metrics.get("by_role"), dict)
        else {}
    )
    role_metrics = {
        "win_rate": 0.0,
        "role_weighted_score": float(
            source.get("role_weighted_score", metrics.get("avg_role_weighted_score", 0.0))
        ),
        "speech_score": float(source.get("speech_score", metrics.get("avg_speech_score", 0.0))),
        "vote_score": float(source.get("vote_score", metrics.get("avg_vote_score", 0.0))),
        "skill_score": float(source.get("skill_score", metrics.get("avg_skill_score", 0.0))),
        "information_score": float(
            source.get("information_score", metrics.get("avg_information_score", 0.0))
        ),
        "cooperation_score": float(
            source.get("cooperation_score", metrics.get("avg_cooperation_score", 0.0))
        ),
        "fallback_rate": float(source.get("fallback_rate", metrics.get("fallback_rate", 0.0))),
        "bad_case_rate": float(source.get("bad_case_rate", 0.0)),
    }
    result = {
        "werewolves": {"win_rate": float(metrics.get("werewolf_win_rate", 0.0))},
        "villagers": {"win_rate": float(metrics.get("villager_win_rate", 0.0))},
    }
    if role is not None:
        result[role] = role_metrics
    return result


def _aggregate_result_by_role(results: list[Any]) -> dict[str, dict[str, float | int]]:
    accum: dict[str, dict[str, float | int]] = {}
    for result in results:
        for role, metrics in getattr(result, "by_role", {}).items():
            state = accum.setdefault(role, _new_role_accum())
            players = int(metrics.get("players", 0))
            state["players"] = int(state["players"]) + players
            state["wins"] = int(state["wins"]) + int(metrics.get("wins", 0))
            state["losses"] = int(state["losses"]) + int(metrics.get("losses", 0))
            state["decision_count"] = int(state["decision_count"]) + int(metrics.get("decision_count", 0))
            state["fallback_count"] = int(state["fallback_count"]) + int(metrics.get("fallback_count", 0))
            state["policy_adjusted_count"] = (
                int(state["policy_adjusted_count"]) + int(metrics.get("policy_adjusted_count", 0))
            )
            state["bad_case_count"] = int(state["bad_case_count"]) + int(metrics.get("bad_case_count", 0))
            for field in (
                "total_score",
                "role_weighted_score",
                "speech_score",
                "vote_score",
                "skill_score",
                "information_score",
                "cooperation_score",
            ):
                state[f"{field}_sum"] = (
                    float(state[f"{field}_sum"]) + float(metrics.get(field, 0.0)) * players
                )
    return {role: finalize_role_metrics(state) for role, state in sorted(accum.items())}


def _win_rate(results: list[Any], team: str) -> float:
    if not results:
        return 0.0
    wins = 0
    for result in results:
        winner = str(getattr(result, "winner", "")).lower()
        if team == "werewolf" and "werewolf" in winner:
            wins += 1
        elif team == "villager" and "villager" in winner:
            wins += 1
    return wins / len(results)


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


async def _call_battle_runner(
    battle_runner: Callable,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Call injected battle runners without forcing new keyword arguments on tests."""
    return await _call_with_supported_kwargs(battle_runner, *args, **kwargs)


async def _call_selfplay_runner(
    selfplay_runner: Callable,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Call injected selfplay runners without requiring every optional kwarg."""
    return await _call_with_supported_kwargs(selfplay_runner, *args, **kwargs)


async def _call_with_supported_kwargs(
    func: Callable,
    *args: Any,
    **kwargs: Any,
) -> Any:
    import inspect

    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return await func(*args, **kwargs)

    accepts_kwargs = any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in signature.parameters.values()
    )
    if accepts_kwargs:
        return await func(*args, **kwargs)

    filtered = {k: v for k, v in kwargs.items() if k in signature.parameters}
    return await func(*args, **filtered)


def _notify(callback: Callable | None, stage: str, data: dict) -> None:
    """Safely invoke the on_progress callback."""
    if callback is None:
        return
    try:
        callback(stage, data)
    except Exception:
        _log.debug("on_progress callback raised for stage %s", stage, exc_info=True)
