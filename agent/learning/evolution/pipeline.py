"""Role evolution pipeline — self-evolution state machine.

Orchestrates the full evolution lifecycle for a single role:
  queued -> training -> consolidating -> applying -> battling -> reviewing
  -> promoted / rejected
Any running stage may transition to -> failed on exception.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import uuid
from typing import Any, Callable

from agent.learning.evolution.applier import apply_proposals
from agent.learning.evolution.battle import _run_battle, _stage_battling
from agent.learning.evolution.config import build_baseline_config, build_composite_skill_dir
from agent.learning.evolution.models import (
    EvolutionRun,
    EvolutionStatus,
    SkillConsolidation,
    SkillVersionConfig,
)
from agent.learning.evolution.state import (
    TERMINAL_STATUSES,
    load_run_state,
    run_dir,
    save_run_state,
    state_path,
    training_run_dir,
)
from agent.learning.evolution.registry import VersionRegistry
from agent.infrastructure.llm import (
    AsyncRateLimiter,
    ModelAdapter,
    default_rate_limiter_from_env,
    limit_model_adapter,
    rate_limit_model_adapter,
)
from agent.common import notify as _notify, beijing_now_iso as _now, write_json as _write_json
from agent.common.run_policy import RunType
from agent.common.paths import DEFAULT as DEFAULT_PATHS

_log = logging.getLogger(__name__)


# Custom exceptions
class InvalidRunStateError(Exception):
    """Raised when an operation is attempted on a run in an invalid state."""


class BaselineChangedError(Exception):
    """Raised when the baseline hash changed since the run started."""


# Scan / recovery
def scan_active_runs() -> list[dict]:
    """Scan all ``runs/evolution/*/state.json`` and return runs with non-terminal status."""
    active: list[dict] = []
    evo_root = DEFAULT_PATHS.evolution_dir
    if not evo_root.exists():
        return active
    for child in sorted(evo_root.iterdir()):
        state_file = child / "state.json"
        if not state_file.is_file():
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            _log.warning("Failed to parse state for %s", child.name, exc_info=True)
            continue
        status = state.get("status", "")
        if status not in TERMINAL_STATUSES:
            active.append(state)
    return active


def recover_interrupted_runs(store: VersionRegistry) -> list[dict]:
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
    for state in scan_active_runs():
        status = state.get("status", "unknown")
        if status not in _ACTIVE_STATUSES:
            continue
        state["status"] = EvolutionStatus.FAILED
        state["error"] = "interrupted"
        state["failed_stage"] = status
        state["updated_at"] = _now()
        evo_root = DEFAULT_PATHS.evolution_dir
        state_file = evo_root / state["run_id"] / "state.json"
        _write_json(state_file, state)
        interrupted.append(state)
        _log.warning("Recovered interrupted run %s (role=%s)", state["run_id"], state.get("role"))
    return interrupted


# ---------------------------------------------------------------------------
# Stage helpers (used to resolve start_from labels)
# ---------------------------------------------------------------------------

_ASYNC_STAGES = [
    EvolutionStatus.TRAINING,
    EvolutionStatus.CONSOLIDATING,
    EvolutionStatus.APPLYING,
    EvolutionStatus.BATTLING,
]


def _resolve_start_from(
    start_from: str | None,
    status: str,
) -> str:
    """Map a *start_from* label (or run status) to the stage to begin from."""
    _LABEL_MAP = {
        "training": EvolutionStatus.TRAINING,
        "consolidating": EvolutionStatus.CONSOLIDATING,
        "applying": EvolutionStatus.APPLYING,
        "battling": EvolutionStatus.BATTLING,
    }
    if start_from and start_from in _LABEL_MAP:
        return _LABEL_MAP[start_from]
    if status in _LABEL_MAP:
        return status
    return EvolutionStatus.TRAINING


def _make_selfplay_config(config_cls: Any, *, run_type: RunType, **kwargs: Any) -> Any:
    """Construct SelfPlayConfig while tolerating lightweight test fakes."""
    try:
        params = inspect.signature(config_cls).parameters
    except (TypeError, ValueError):
        params = {}
    if "run_type" in params:
        return config_cls(**kwargs, run_type=run_type)
    config = config_cls(**kwargs)
    try:
        setattr(config, "run_type", run_type)
    except Exception:
        pass
    return config


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def run_evolution(
    store: VersionRegistry,
    role: str | None = None,
    *,
    run_id: str | None = None,
    start_from: str = "training",
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
    pattern_engine: "PatternEngine | None" = None,
) -> EvolutionRun:
    """Run the evolution pipeline for *role*.

    When *run_id* is ``None`` a fresh run is created and all stages are
    executed from the beginning (or from *start_from*).

    When *run_id* is provided an existing run is loaded from disk.  By
    default the run resumes from the stage where it last failed.  Pass
    *start_from* explicitly to override that (e.g. ``"consolidating"`` to
    re-run consolidation using existing training data).

    Valid *start_from* values: ``"training"``, ``"consolidating"``,
    ``"applying"``, ``"battling"``.

    Returns the :class:`EvolutionRun` in its terminal or reviewing state.
    On failure the run is persisted with ``status=failed`` and re-raised.
    """
    # Lazy defaults — avoid import cycles at module level
    if selfplay_runner is None:
        from agent.learning.evolution.games import run_selfplay as _default_selfplay
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

    # -- Load existing run or create fresh ---------------------------------
    if run_id is not None:
        state = load_run_state(DEFAULT_PATHS, run_id)
        if state is None:
            raise KeyError(f"Run {run_id} not found on disk")

        failed_stage = state.get("failed_stage") or state.get("status")
        if failed_stage in TERMINAL_STATUSES and failed_stage != EvolutionStatus.FAILED:
            raise InvalidRunStateError(f"Run {run_id} is in terminal state {failed_stage}")

        if role is None:
            role = state["role"]
        training_games = state.get("training_games", training_games)
        battle_games = state.get("battle_games", battle_games)

        baseline_data = state.get("baseline_config")
        baseline_config = (
            SkillVersionConfig.from_dict(baseline_data)
            if baseline_data else build_baseline_config(store)
        )
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

        # Determine starting stage
        stage = _resolve_start_from(start_from, failed_stage)
    else:
        # Fresh run — validate role is provided
        if role is None:
            raise ValueError("role is required when run_id is not provided")

        baseline_config = baseline_config or build_baseline_config(store)
        try:
            parent_hash = baseline_config.role_versions[role]
        except KeyError as exc:
            raise KeyError(f"Role '{role}' not found in baseline config") from exc
        store.get_package(role, parent_hash)

        run_id = f"evo_{uuid.uuid4().hex[:12]}"
        rd = run_dir(DEFAULT_PATHS, run_id)
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
        save_run_state(run)

        stage = _resolve_start_from(start_from, EvolutionStatus.QUEUED)

    # -- Execute pipeline from *stage* onward ------------------------------
    try:
        if stage == EvolutionStatus.TRAINING:
            run = await _stage_training(
                run, store, training_games, limited_model, game_concurrency,
                llm_semaphore, llm_rate_limiter,
                selfplay_runner, on_progress,
            )

        # Pattern lifecycle management — prune stale/low-confidence patterns
        if pattern_engine is not None:
            gc_result = pattern_engine.run_lifecycle_gc()
            if gc_result.get("archived") or gc_result.get("deprecated"):
                _log.info("Pattern GC: archived=%d, deprecated=%d",
                          len(gc_result.get("archived", [])),
                          len(gc_result.get("deprecated", [])))

        if stage in (EvolutionStatus.TRAINING, EvolutionStatus.CONSOLIDATING):
            run = await _stage_consolidating(
                run, store, limited_model, consolidator, on_progress,
            )

        if stage in (
            EvolutionStatus.TRAINING,
            EvolutionStatus.CONSOLIDATING,
            EvolutionStatus.APPLYING,
        ):
            run = await _stage_applying(
                run, store, limited_model, applier,
            )

        run = await _stage_battling(
            run, store, battle_games, limited_model, game_concurrency,
            llm_semaphore, llm_rate_limiter,
            selfplay_runner, battle_runner, on_progress,
        )

        run.status = EvolutionStatus.REVIEWING
        save_run_state(run)
        _notify(on_progress, "reviewing", {"run_id": run.run_id})

    except Exception as exc:
        failed_stage = run.status
        _log.exception("Evolution run %s failed at stage %s", run.run_id, failed_stage)
        run.status = EvolutionStatus.FAILED
        run.errors.append(str(exc))
        save_run_state(run)
        path = state_path(DEFAULT_PATHS, run.run_id)
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
            s["failed_stage"] = failed_stage
            _write_json(path, s)
        except Exception:
            _log.debug("failed to patch failed_stage for %s", run.run_id, exc_info=True)
        raise

    return run


# ---------------------------------------------------------------------------
# Backward-compatible thin wrappers
# ---------------------------------------------------------------------------


async def resume_evolution(
    store: VersionRegistry,
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
    pattern_engine: "PatternEngine | None" = None,
) -> EvolutionRun:
    """Resume a failed evolution run from the failed stage.

    Thin wrapper around :func:`run_evolution` with ``run_id`` set.
    Training and battle games that already completed are automatically
    skipped by the selfplay checkpoint mechanism.
    """
    return await run_evolution(
        store,
        run_id=run_id,
        model_adapter=model_adapter,
        game_concurrency=game_concurrency,
        llm_semaphore=llm_semaphore,
        llm_rate_limiter=llm_rate_limiter,
        on_progress=on_progress,
        selfplay_runner=selfplay_runner,
        consolidator=consolidator,
        applier=applier,
        battle_runner=battle_runner,
        pattern_engine=pattern_engine,
    )


async def rerun_from_consolidation(
    store: VersionRegistry,
    run_id: str,
    model_adapter: ModelAdapter | None = None,
    game_concurrency: int = 1,
    llm_semaphore: asyncio.Semaphore | None = None,
    llm_rate_limiter: AsyncRateLimiter | None = None,
    on_progress: Callable[[str, dict], None] | None = None,
    battle_runner: Callable | None = None,
    pattern_engine: "PatternEngine | None" = None,
) -> EvolutionRun:
    """Re-run from consolidation stage using existing training data.

    Thin wrapper around :func:`run_evolution` with
    ``run_id`` set and ``start_from="consolidating"``.
    """
    return await run_evolution(
        store,
        run_id=run_id,
        start_from="consolidating",
        game_concurrency=game_concurrency,
        llm_semaphore=llm_semaphore,
        llm_rate_limiter=llm_rate_limiter,
        on_progress=on_progress,
        battle_runner=battle_runner,
        pattern_engine=pattern_engine,
    )


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------


async def _stage_training(
    run: EvolutionRun,
    store: VersionRegistry,
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
    save_run_state(run)
    _notify(on_progress, "training", {"run_id": run.run_id, "games": training_games})

    from agent.learning.evolution.games import SelfPlayConfig

    output_run_dir = run_dir(DEFAULT_PATHS, run.run_id)

    baseline_config = run.baseline_config or build_baseline_config(store)
    skill_dir = build_composite_skill_dir(store, baseline_config)

    config = _make_selfplay_config(
        SelfPlayConfig,
        games=training_games,
        output_dir=output_run_dir,
        enable_mid_memory=True,
        enable_long_term_consolidation=False,  # we consolidate manually in stage 2
        skill_dir=skill_dir,
        game_concurrency=game_concurrency,
        db_path=DEFAULT_PATHS.data_dir / "wolf.db",
        run_type=RunType.EVOLUTION_TRAINING,
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
        result = await selfplay_runner(
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
            save_run_state(run)
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
    store: VersionRegistry,
    model_adapter: ModelAdapter | None,
    consolidator: Callable,
    on_progress: Callable | None = None,
) -> EvolutionRun:
    """Stage 2: Consolidate mid-memory into skill proposals."""
    run.status = EvolutionStatus.CONSOLIDATING
    save_run_state(run)
    _notify(on_progress, "consolidating", {"run_id": run.run_id})

    output_run_dir = training_run_dir(run) or run_dir(DEFAULT_PATHS, run.run_id)

    consolidation: SkillConsolidation = await consolidator(
        output_run_dir, run.role, model_adapter,
        run_id=run.run_id,
        parent_hash=run.parent_hash,
        window=run.training_games,
        max_proposals=3,
        skill_root=store.get_skill_dir(run.role, run.parent_hash),
        store=store,
    )
    run.proposals = consolidation
    save_run_state(run)
    return run


async def _stage_applying(
    run: EvolutionRun,
    store: VersionRegistry,
    model_adapter: ModelAdapter | None,
    applier: Callable,
) -> EvolutionRun:
    """Stage 3: Apply proposals to produce candidate skill set."""
    run.status = EvolutionStatus.APPLYING
    save_run_state(run)

    if run.proposals is None or not run.proposals.proposals:
        _log.info("No proposals to apply — skipping apply stage")
        # Use parent hash as candidate (no change)
        run.candidate_hash = run.parent_hash
        run.diff = []
        save_run_state(run)
        return run

    # Load current skills from the baseline version
    current_skills = store.read_skill_contents(run.role, run.parent_hash)

    new_skills, diffs = await applier(current_skills, run.proposals, model_adapter)

    # Save candidate version to store
    candidate_hash = await store.publish_skills(
        role=run.role,
        skill_contents=new_skills,
        parent_id=run.parent_hash,
        source="evolution",
        run_id=run.run_id,
    )

    run.candidate_hash = candidate_hash
    run.diff = diffs

    # Persist diff.json alongside state
    diff_path = run_dir(DEFAULT_PATHS, run.run_id) / "diff.json"
    _write_json(diff_path, {"diffs": [d.to_dict() for d in diffs]})

    save_run_state(run)
    return run


# Promote / reject
async def promote(run: EvolutionRun, store: VersionRegistry) -> None:
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
    current_baseline = store.get_baseline(run.role)

    # Baseline already equals candidate -> just set promoted
    if current_baseline == run.candidate_hash:
        run.status = EvolutionStatus.PROMOTED
        save_run_state(run)
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
        version_id=run.candidate_hash,
        expected_current=run.parent_hash,
    )
    if not success:
        raise BaselineChangedError(
            f"CAS failed for {run.role}: expected {run.parent_hash}"
        )

    run.status = EvolutionStatus.PROMOTED
    save_run_state(run)


async def reject(run: EvolutionRun, store: VersionRegistry) -> None:
    """Reject a reviewing run.

    Idempotent: already rejected -> return.
    Raises InvalidRunStateError on terminal conflict or wrong state.

    Saves the failed proposals to the rejected buffer so future
    consolidations can learn from the failure.
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

    # Save proposals to rejected buffer before changing status
    if run.proposals is not None and run.proposals.proposals:
        try:
            await store.save_rejected(
                run.role,
                [p.to_dict() for p in run.proposals.proposals
                 if getattr(p, "status", "proposed") != "skipped"],
                run.battle_result,
            )
        except Exception:
            _log.error(
                "Failed to save rejected proposals for %s/%s",
                run.role, run.run_id, exc_info=True,
            )

    run.status = EvolutionStatus.REJECTED
    save_run_state(run)
