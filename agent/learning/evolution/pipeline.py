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
from typing import Any, Callable

from agent.learning.evolution.applier import apply_proposals
from agent.learning.evolution.battle import _run_battle, _stage_battling
from agent.learning.evolution.config import build_baseline_config
from agent.learning.evolution.invocation import call_selfplay_runner
from agent.learning.evolution.models import (
    EvolutionRun,
    EvolutionStatus,
    SkillConsolidation,
    SkillVersionConfig,
)
from agent.learning.evolution.workspace import build_composite_skill_dir
from agent.learning.evolution.state import (
    TERMINAL_STATUSES,
    load_run_state,
    run_dir,
    save_run_state,
    state_path,
    training_run_dir,
)
from agent.learning.evolution.store import VersionStore
from agent.infrastructure.llm import (
    AsyncRateLimiter,
    ModelAdapter,
    default_rate_limiter_from_env,
    limit_model_adapter,
    rate_limit_model_adapter,
)
from agent.common import notify as _notify, utc_now_iso as _now, write_json as _write_json

_log = logging.getLogger(__name__)


# Custom exceptions
class InvalidRunStateError(Exception):
    """Raised when an operation is attempted on a run in an invalid state."""


class BaselineChangedError(Exception):
    """Raised when the baseline hash changed since the run started."""


# Scan / recovery
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
        if status not in TERMINAL_STATUSES:
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


# Main pipeline
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
        from agent.learning.selfplay import run_selfplay as _default_selfplay
        selfplay_runner = _default_selfplay
    if consolidator is None:
        from agent.learning.evolution.consolidation import consolidate_for_role as _default_consolidator
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
    rd = run_dir(store, run_id)
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
    save_run_state(run, store)

    try:
        # Stage 1: training
        run = await _stage_training(
            run, store, training_games, limited_model, game_concurrency,
            llm_semaphore, llm_rate_limiter,
            selfplay_runner, on_progress,
        )

        # Stage 2: consolidating
        run = await _stage_consolidating(
            run, store, limited_model, consolidator, on_progress,
        )

        # Stage 3: applying
        run = await _stage_applying(
            run, store, limited_model, applier,
        )

        # Stage 4: battling
        run = await _stage_battling(
            run, store, battle_games, limited_model, game_concurrency,
            llm_semaphore, llm_rate_limiter,
            selfplay_runner, battle_runner, on_progress,
        )

        # Stage 5: reviewing
        run.status = EvolutionStatus.REVIEWING
        save_run_state(run, store)
        _notify(on_progress, "reviewing", {"run_id": run.run_id})

    except Exception as exc:
        failed_stage = run.status
        _log.exception("Evolution run %s failed at stage %s", run.run_id, failed_stage)
        run.status = EvolutionStatus.FAILED
        run.errors.append(str(exc))
        save_run_state(run, store)
        path = state_path(store, run.run_id)
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            state["failed_stage"] = failed_stage
            _write_json(path, state)
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
    state = load_run_state(store, run_id)
    if state is None:
        raise KeyError(f"Run {run_id} not found on disk")

    failed_stage = state.get("failed_stage") or state.get("status")
    if failed_stage in TERMINAL_STATUSES and failed_stage != EvolutionStatus.FAILED:
        raise InvalidRunStateError(f"Run {run_id} is in terminal state {failed_stage}")

    role = state["role"]
    training_games = state.get("training_games", 20)
    battle_games = state.get("battle_games", 10)

    # Reconstruct EvolutionRun from saved state
    from agent.learning.evolution.models import SkillVersionConfig
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
        from agent.learning.selfplay import run_selfplay as _default_selfplay
        selfplay_runner = _default_selfplay
    if consolidator is None:
        from agent.learning.evolution.consolidation import consolidate_for_role as _default_consolidator
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
        save_run_state(run, store)
        _notify(on_progress, "reviewing", {"run_id": run.run_id})

    except Exception as exc:
        failed_stage_now = run.status
        _log.exception("Resumed evolution run %s failed at stage %s", run.run_id, failed_stage_now)
        run.status = EvolutionStatus.FAILED
        run.errors.append(str(exc))
        save_run_state(run, store)
        path = state_path(store, run.run_id)
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
            s["failed_stage"] = failed_stage_now
            _write_json(path, s)
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
    state = load_run_state(store, run_id)
    if state is None:
        raise KeyError(f"Run {run_id} not found on disk")

    role = state["role"]
    training_games = state.get("training_games", 20)
    battle_games = state.get("battle_games", 10)

    from agent.learning.evolution.models import SkillVersionConfig
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

    from agent.learning.evolution.consolidation import consolidate_for_role as _default_consolidator
    if battle_runner is None:
        battle_runner = _run_battle

    llm_rate_limiter = llm_rate_limiter or default_rate_limiter_from_env()
    if model_adapter is None:
        from agent.api.factory import load_llm_client
        model_adapter = load_llm_client()
    limited_model = limit_model_adapter(model_adapter, llm_semaphore)
    limited_model = rate_limit_model_adapter(limited_model, llm_rate_limiter)

    from agent.learning.selfplay import run_selfplay as _default_selfplay

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
        save_run_state(run, store)
        _notify(on_progress, "reviewing", {"run_id": run.run_id})
    except Exception as exc:
        _log.exception("Rerun from consolidation failed for %s", run_id)
        run.status = EvolutionStatus.FAILED
        run.errors.append(str(exc))
        save_run_state(run, store)
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
    save_run_state(run, store)
    _notify(on_progress, "training", {"run_id": run.run_id, "games": training_games})

    from agent.learning.selfplay import SelfPlayConfig

    output_run_dir = run_dir(store, run.run_id)

    baseline_config = run.baseline_config or build_baseline_config(store)
    skill_dir = build_composite_skill_dir(store, baseline_config)

    config = SelfPlayConfig(
        games=training_games,
        output_dir=output_run_dir,
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
        result = await call_selfplay_runner(
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
            run.training_output_dir = str(output_run_dir / training_run_id)
            save_run_state(run, store)
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
    save_run_state(run, store)
    _notify(on_progress, "consolidating", {"run_id": run.run_id})

    output_run_dir = training_run_dir(run, store) or run_dir(store, run.run_id)

    consolidation: SkillConsolidation = await consolidator(
        output_run_dir, run.role, model_adapter,
        run_id=run.run_id,
        parent_hash=run.parent_hash,
        skill_root=store.get_skill_dir(run.role, run.parent_hash),
    )
    run.proposals = consolidation
    save_run_state(run, store)
    return run


async def _stage_applying(
    run: EvolutionRun,
    store: VersionStore,
    model_adapter: ModelAdapter | None,
    applier: Callable,
) -> EvolutionRun:
    """Stage 3: Apply proposals to produce candidate skill set."""
    run.status = EvolutionStatus.APPLYING
    save_run_state(run, store)

    if run.proposals is None or not run.proposals.proposals:
        _log.info("No proposals to apply — skipping apply stage")
        # Use parent hash as candidate (no change)
        run.candidate_hash = run.parent_hash
        run.diff = []
        save_run_state(run, store)
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
    diff_path = run_dir(store, run.run_id) / "diff.json"
    _write_json(diff_path, {"diffs": [d.to_dict() for d in diffs]})

    save_run_state(run, store)
    return run


# Promote / reject
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
        save_run_state(run, store)
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
    save_run_state(run, store)


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
    save_run_state(run, store)

