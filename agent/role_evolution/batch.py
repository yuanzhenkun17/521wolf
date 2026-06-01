"""Batch role evolution.

Runs multiple role-evolution jobs against one frozen baseline snapshot, then
optionally evaluates and promotes the accepted candidate pack.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from agent.role_evolution.config import build_baseline_config
from agent.role_evolution.models import EvolutionRun, SkillVersionConfig
from agent.role_evolution.pipeline import _run_config_battle, run_evolution
from agent.role_evolution.store import VersionStore
from agent.runtime.model import AsyncRateLimiter, ModelAdapter, limit_model_adapter, rate_limit_model_adapter

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchEvolutionResult:
    batch_id: str
    baseline_config: SkillVersionConfig
    runs: list[EvolutionRun] = field(default_factory=list)
    accepted_roles: list[str] = field(default_factory=list)
    rejected_roles: list[str] = field(default_factory=list)
    combined_config: SkillVersionConfig | None = None
    combined_battle_result: dict[str, Any] | None = None
    combined_passed: bool = False
    promoted_roles: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "baseline_config": self.baseline_config.to_dict(),
            "runs": [r.to_dict() for r in self.runs],
            "accepted_roles": list(self.accepted_roles),
            "rejected_roles": list(self.rejected_roles),
            "combined_config": self.combined_config.to_dict()
            if self.combined_config is not None else None,
            "combined_battle_result": self.combined_battle_result,
            "combined_passed": self.combined_passed,
            "promoted_roles": list(self.promoted_roles),
            "errors": list(self.errors),
        }


async def run_batch_evolution(
    *,
    store: VersionStore,
    roles: list[str] | None = None,
    training_games: int = 20,
    battle_games: int = 10,
    role_concurrency: int = 2,
    game_concurrency: int = 1,
    llm_concurrency: int = 20,
    llm_rpm: int = 60,
    model_adapter: ModelAdapter | None = None,
    auto_promote: bool = False,
    on_progress: Callable[[str, dict], None] | None = None,
    selfplay_runner: Callable | None = None,
    consolidator: Callable | None = None,
    applier: Callable | None = None,
    battle_runner: Callable | None = None,
) -> BatchEvolutionResult:
    """Run multiple role evolutions from one frozen baseline snapshot."""
    batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    baseline_config = build_baseline_config(store)
    selected_roles = roles or sorted(baseline_config.role_versions)
    missing = [role for role in selected_roles if role not in baseline_config.role_versions]
    if missing:
        raise KeyError(f"Roles not found in baseline config: {missing}")

    llm_semaphore = asyncio.Semaphore(llm_concurrency)
    llm_rate_limiter = AsyncRateLimiter(llm_rpm) if llm_rpm > 0 else None
    role_limiter = asyncio.Semaphore(max(1, role_concurrency))
    limited_model = (
        limit_model_adapter(model_adapter, llm_semaphore)
        if model_adapter is not None else None
    )
    if limited_model is not None:
        limited_model = rate_limit_model_adapter(limited_model, llm_rate_limiter)

    result = BatchEvolutionResult(
        batch_id=batch_id,
        baseline_config=baseline_config,
    )
    _notify(on_progress, "batch_started", {
        "batch_id": batch_id,
        "roles": selected_roles,
        "baseline_config": baseline_config.to_dict(),
    })

    async def _run_role(role: str) -> EvolutionRun:
        async with role_limiter:
            _notify(on_progress, "role_started", {"batch_id": batch_id, "role": role})
            run = await run_evolution(
                store=store,
                role=role,
                training_games=training_games,
                battle_games=battle_games,
                model_adapter=model_adapter,
                baseline_config=baseline_config,
                game_concurrency=game_concurrency,
                llm_semaphore=llm_semaphore,
                llm_rate_limiter=llm_rate_limiter,
                on_progress=lambda stage, data: _notify(
                    on_progress,
                    f"role_{stage}",
                    {"batch_id": batch_id, "role": role, **data},
                ),
                selfplay_runner=selfplay_runner,
                consolidator=consolidator,
                applier=applier,
                battle_runner=battle_runner,
            )
            _notify(on_progress, "role_finished", {
                "batch_id": batch_id,
                "role": role,
                "run_id": run.run_id,
                "candidate_hash": run.candidate_hash,
                "status": run.status,
            })
            return run

    result.runs = await asyncio.gather(*(_run_role(role) for role in selected_roles))

    for run in result.runs:
        if _single_candidate_passes(run):
            result.accepted_roles.append(run.role)
        else:
            result.rejected_roles.append(run.role)

    if not result.accepted_roles:
        _notify(on_progress, "batch_reviewing", result.to_dict())
        return result

    role_versions = dict(baseline_config.role_versions)
    for run in result.runs:
        if run.role in result.accepted_roles and run.candidate_hash is not None:
            role_versions[run.role] = run.candidate_hash

    combined_config = SkillVersionConfig(
        name=f"{batch_id}-combined",
        created_at=datetime.now(timezone.utc).isoformat(),
        role_versions=role_versions,
        notes=[
            f"combined accepted candidates from {batch_id}",
            f"accepted roles: {', '.join(result.accepted_roles)}",
        ],
    )
    result.combined_config = combined_config
    _notify(on_progress, "combined_battle_started", {
        "batch_id": batch_id,
        "accepted_roles": result.accepted_roles,
    })

    if selfplay_runner is None:
        from agent.evaluation.selfplay import run_selfplay as selfplay_runner

    result.combined_battle_result = await _run_config_battle(
        store=store,
        baseline_config=baseline_config,
        candidate_config=combined_config,
        battle_games=battle_games,
        model_adapter=limited_model,
        selfplay_runner=selfplay_runner,
        on_progress=lambda stage, data: _notify(
            on_progress,
            f"combined_{stage}",
            {"batch_id": batch_id, **data},
        ),
        seed_start=20_000,
        game_concurrency=game_concurrency,
        llm_semaphore=llm_semaphore,
        llm_rate_limiter=llm_rate_limiter,
    )
    result.combined_passed = _battle_summary_passes(result.combined_battle_result)

    if auto_promote and result.combined_passed:
        await _promote_accepted_roles(store, baseline_config, result)

    _notify(on_progress, "batch_reviewing", result.to_dict())
    return result


async def promote_batch_result(
    *,
    store: VersionStore,
    result: BatchEvolutionResult,
) -> BatchEvolutionResult:
    """Promote accepted roles from an already reviewed batch result."""
    if not result.combined_passed:
        result.errors.append("combined battle did not pass")
        return result
    await _promote_accepted_roles(store, result.baseline_config, result)
    return result


def _single_candidate_passes(run: EvolutionRun) -> bool:
    if run.candidate_hash is None or run.candidate_hash == run.parent_hash:
        return False
    if not run.battle_result:
        return False
    return _battle_summary_passes(run.battle_result, role=run.role)


def _battle_summary_passes(summary: dict[str, Any], role: str | None = None) -> bool:
    baseline = summary.get("baseline", {})
    candidate = summary.get("candidate", {})
    if not baseline or not candidate:
        return False
    base_metrics = _select_metrics(baseline, role)
    cand_metrics = _select_metrics(candidate, role)
    base_score = float(base_metrics.get("role_weighted_score", 0.0))
    cand_score = float(cand_metrics.get("role_weighted_score", 0.0))
    base_fallback = float(base_metrics.get("fallback_rate", 0.0))
    cand_fallback = float(cand_metrics.get("fallback_rate", 0.0))
    return cand_score >= base_score and cand_fallback <= base_fallback


def _select_metrics(summary_side: dict[str, Any], role: str | None) -> dict[str, Any]:
    if role is not None:
        role_metrics = summary_side.get("by_role", {}).get(role)
        if role_metrics:
            return role_metrics
    return {
        "role_weighted_score": summary_side.get("avg_role_weighted_score", 0.0),
        "fallback_rate": summary_side.get("fallback_rate", 0.0),
    }


async def _promote_accepted_roles(
    store: VersionStore,
    baseline_config: SkillVersionConfig,
    result: BatchEvolutionResult,
) -> None:
    candidate_by_role = {
        run.role: run.candidate_hash
        for run in result.runs
        if run.role in result.accepted_roles and run.candidate_hash is not None
    }

    drifted = []
    for role, expected_hash in baseline_config.role_versions.items():
        if role not in candidate_by_role:
            continue
        current = store.get_history(role).baseline
        if current != expected_hash:
            drifted.append((role, expected_hash, current))
    if drifted:
        result.errors.append(f"baseline changed before promote: {drifted}")
        return

    for role, candidate_hash in candidate_by_role.items():
        expected_hash = baseline_config.role_versions[role]
        success = await store.set_baseline(
            role=role,
            target_hash=candidate_hash,
            expected_current=expected_hash,
        )
        if success:
            result.promoted_roles.append(role)
        else:
            result.errors.append(f"CAS failed for {role}: expected {expected_hash}")


def _notify(callback: Callable[[str, dict], None] | None, stage: str, data: dict) -> None:
    if callback is None:
        return
    try:
        callback(stage, data)
    except Exception:
        _log.debug("callback raised during stage %s", stage, exc_info=True)
