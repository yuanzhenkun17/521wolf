"""Evolution battle runner — A/B comparison of skill versions."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

from agent.learning_v2.stats import new_role_accum, finalize_role_metrics
from agent.learning_v2.evolution.config import (
    build_baseline_config,
    build_composite_skill_dir,
    build_role_override_from_config,
)
from agent.learning_v2.evolution.models import EvolutionRun, EvolutionStatus, SkillVersionConfig
from agent.learning_v2.evolution.state import run_dir, save_run_state
from agent.learning_v2.evolution.store import VersionStore
from agent.infrastructure.llm import AsyncRateLimiter, ModelAdapter
from agent.common import notify as _notify, write_json as _write_json
from agent.common.paths import DEFAULT as DEFAULT_PATHS

_log = logging.getLogger(__name__)


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
    save_run_state(run)
    _notify(on_progress, "battling", {"run_id": run.run_id, "games": battle_games})

    if run.candidate_hash == run.parent_hash:
        _log.info("Candidate equals parent — skipping battle")
        run.battle_result = {"skipped": True, "reason": "no_changes"}
        save_run_state(run)
        return run

    battle_result = await battle_runner(
        store, run.role, run.candidate_hash, battle_games,
        model_adapter, selfplay_runner, on_progress,
        baseline_config=run.baseline_config,
        game_concurrency=game_concurrency,
        llm_semaphore=llm_semaphore,
        llm_rate_limiter=llm_rate_limiter,
        output_dir=run_dir(DEFAULT_PATHS, run.run_id) / "battle",
    )
    run.battle_result = battle_result

    # Persist battle summary
    battle_path = run_dir(DEFAULT_PATHS, run.run_id) / "battle_summary.json"
    _write_json(battle_path, battle_result)

    save_run_state(run)
    return run


# Battle implementation


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

    return await run_config_battle(
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


async def run_config_battle(
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

    from agent.learning_v2.evolution.games import SelfPlayConfig

    # Build composite skill directories for each side
    skill_dir_a = build_composite_skill_dir(store, baseline_config)
    skill_dir_b = build_composite_skill_dir(store, candidate_config)

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
            output_dir=(output_dir / "baseline") if output_dir is not None else DEFAULT_PATHS.selfplay_dir,
            enable_mid_memory=False,
            enable_long_term_consolidation=False,
            skill_dir=skill_dir_a,
            game_concurrency=game_concurrency,
            db_path=DEFAULT_PATHS.data_dir / "wolf.db",
        )
        cfg_b = SelfPlayConfig(
            games=battle_games,
            seed_start=seed_start,
            output_dir=(output_dir / "candidate") if output_dir is not None else DEFAULT_PATHS.selfplay_dir,
            enable_mid_memory=False,
            enable_long_term_consolidation=False,
            skill_dir=skill_dir_b,
            game_concurrency=game_concurrency,
            db_path=DEFAULT_PATHS.data_dir / "wolf.db",
        )
        result_a, result_b = await asyncio.gather(
            selfplay_runner(
                cfg_a,
                model=model_adapter,
                on_game_complete=_on_game_a,
                llm_semaphore=llm_semaphore,
                llm_rate_limiter=llm_rate_limiter,
            ),
            selfplay_runner(
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

    # Significance check: candidate must be meaningfully better
    summary["significant"] = _is_significant_improvement(summary, role, battle_games)

    return summary


def _is_significant_improvement(
    summary: dict[str, Any],
    role: str | None,
    battle_games: int,
) -> bool:
    """Check if candidate improvement over baseline is significant.

    Criteria (inspired by SkillOpt's strict validation gate):
    1. Candidate role_weighted_score must be >= baseline + 0.05 (5% absolute)
    2. Candidate target-side win rate must be >= baseline + 0.10 (10% absolute)
    """
    baseline_metrics = summary.get("baseline_metrics", {})
    candidate_metrics = summary.get("candidate_metrics", {})

    # Check role_weighted_score improvement
    baseline_score = 0.0
    candidate_score = 0.0
    if role and role in baseline_metrics:
        baseline_score = baseline_metrics[role].get("role_weighted_score", 0.0)
        candidate_score = candidate_metrics.get(role, {}).get("role_weighted_score", 0.0)

    score_improved = candidate_score >= baseline_score + 0.05

    # Check win rate improvement for the target role's side
    if role in ("werewolf", "white_wolf_king"):
        baseline_wr = summary.get("baseline", {}).get("werewolf_win_rate", 0.0)
        candidate_wr = summary.get("candidate", {}).get("werewolf_win_rate", 0.0)
    else:
        baseline_wr = summary.get("baseline", {}).get("villager_win_rate", 0.0)
        candidate_wr = summary.get("candidate", {}).get("villager_win_rate", 0.0)

    wr_improved = candidate_wr >= baseline_wr + 0.10

    # Both criteria must be met for significance
    return score_improved and wr_improved


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
    total_llm_errors = sum(getattr(r, "llm_error_count", 0) for r in valid)
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
        "llm_error_rate": total_llm_errors / total_decisions if total_decisions else 0.0,
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
            state = accum.setdefault(role, new_role_accum())
            players = int(metrics.get("players", 0))
            state["players"] = int(state["players"]) + players
            state["wins"] = int(state["wins"]) + int(metrics.get("wins", 0))
            state["losses"] = int(state["losses"]) + int(metrics.get("losses", 0))
            state["decision_count"] = int(state["decision_count"]) + int(metrics.get("decision_count", 0))
            state["fallback_count"] = int(state["fallback_count"]) + int(metrics.get("fallback_count", 0))
            state["llm_error_count"] = int(state["llm_error_count"]) + int(metrics.get("llm_error_count", 0))
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