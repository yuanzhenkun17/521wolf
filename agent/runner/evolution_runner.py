"""Evolution runner for training and A/B battle games.

Provides two entry points:
- ``run_training_games``: batch of games with fixed seeds for reproducible training.
- ``run_ab_battle``: baseline vs candidate comparison with matched seeds.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.common import beijing_now_iso
from agent.runner.shared import create_agents_for_game, create_engine

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TrainingConfig:
    """Configuration for evolution training games."""

    num_games: int = 20
    seed_start: int = 0
    max_days: int = 20
    enable_sheriff: bool = True
    skill_dir: Path | None = None
    role_skill_dirs: dict[str, Path] | None = None
    model: Any = None
    game_concurrency: int = 3
    on_game_complete: Callable[[int, Any], None] | None = None
    enable_mid_memory: bool = True
    output_dir: Path | None = None
    db_path: Path | None = None


@dataclass
class TrainingResult:
    """Result of a training run."""

    games: list[dict[str, Any]]
    total_games: int
    completed: int
    errored: int
    started_at: str
    finished_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "games": self.games,
            "total_games": self.total_games,
            "completed": self.completed,
            "errored": self.errored,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class ABConfig:
    """Configuration for A/B battle."""

    num_games: int = 10
    seed_start: int = 10000
    max_days: int = 20
    enable_sheriff: bool = True
    baseline_skill_dir: Path | None = None
    candidate_skill_dir: Path | None = None
    baseline_role_skill_dirs: dict[str, Path] | None = None
    candidate_role_skill_dirs: dict[str, Path] | None = None
    model: Any = None
    game_concurrency: int = 3
    output_dir: Path | None = None
    db_path: Path | None = None


@dataclass
class ABResult:
    """Result of A/B battle."""

    baseline_results: list[dict[str, Any]]
    candidate_results: list[dict[str, Any]]
    summary: dict[str, Any]
    significant: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_results": self.baseline_results,
            "candidate_results": self.candidate_results,
            "summary": self.summary,
            "significant": self.significant,
        }


# ---------------------------------------------------------------------------
# EvolutionRunner
# ---------------------------------------------------------------------------


class EvolutionRunner:
    """Runner for evolution training and A/B battle games.

    - AI-only (no human players)
    - Fixed seeds (reproducible)
    - No UI event callbacks
    - Triggers mid-memory analysis per game when enabled
    """

    def __init__(self, *, paths: Any | None = None) -> None:
        self._paths = paths

    def _resolve_paths(self) -> Any:
        if self._paths is not None:
            return self._paths
        from agent.common.paths import DEFAULT as DEFAULT_PATHS
        return DEFAULT_PATHS

    async def run_training_games(self, config: TrainingConfig) -> TrainingResult:
        """Run a batch of training games with fixed seeds.

        Each game gets ``seed = config.seed_start + i`` for reproducibility.
        Games run concurrently up to ``config.game_concurrency`` at a time.
        """
        from agent.api.factory import load_llm_client
        from agent.common.paths import DEFAULT as DEFAULT_PATHS

        paths = self._resolve_paths()
        started_at = beijing_now_iso()

        # Resolve output directory
        run_dir = config.output_dir
        if run_dir is None:
            from agent.common.time import beijing_now_str
            run_id = f"train_{beijing_now_str('%Y%m%d_%H%M%S')}"
            run_dir = paths.selfplay_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Resolve LLM client
        model = config.model
        if model is None:
            model = load_llm_client()

        db_path = config.db_path if config.db_path is not None else paths.evolution_db_path

        results: list[dict[str, Any] | None] = [None] * config.num_games

        async def _run_index(i: int) -> None:
            seed = config.seed_start + i
            game_id = f"game_{i + 1:03d}"
            game_dir = run_dir / "games" / game_id
            game_dir.mkdir(parents=True, exist_ok=True)

            result = await _run_single_training_game(
                seed=seed,
                game_id=game_id,
                game_dir=game_dir,
                model=model,
                max_days=config.max_days,
                enable_sheriff=config.enable_sheriff,
                skill_dir=config.skill_dir,
                role_skill_dirs=config.role_skill_dirs,
                enable_mid_memory=config.enable_mid_memory,
                db_path=db_path,
                paths=paths,
            )

            results[i] = result
            if config.on_game_complete is not None:
                try:
                    config.on_game_complete(i, result)
                except Exception:
                    _log.debug("on_game_complete callback raised for game %s", game_id, exc_info=True)

        if config.num_games > 0:
            concurrency = max(1, min(config.game_concurrency, config.num_games))
            semaphore = asyncio.Semaphore(concurrency)

            async def _limited(i: int) -> None:
                async with semaphore:
                    await _run_index(i)

            await asyncio.gather(*(_limited(i) for i in range(config.num_games)))

        completed_results = [r for r in results if r is not None]
        errored = sum(1 for r in completed_results if r.get("error"))
        finished_at = beijing_now_iso()

        # Write summary
        training_result = TrainingResult(
            games=completed_results,
            total_games=config.num_games,
            completed=len(completed_results) - errored,
            errored=errored,
            started_at=started_at,
            finished_at=finished_at,
        )
        _write_json_sync(run_dir / "summary.json", training_result.to_dict())
        return training_result

    async def run_ab_battle(self, config: ABConfig) -> ABResult:
        """Run A/B comparison: baseline vs candidate with matched seeds.

        Both sides play ``config.num_games`` games with identical seeds
        (``seed_start`` to ``seed_start + num_games - 1``). Results are
        compared and a significance check is applied.
        """
        from agent.api.factory import load_llm_client

        paths = self._resolve_paths()
        model = config.model
        if model is None:
            model = load_llm_client()

        db_path = config.db_path if config.db_path is not None else paths.evolution_db_path

        # Output directories
        output_dir = config.output_dir
        if output_dir is None:
            from agent.common.time import beijing_now_str
            run_id = f"battle_{beijing_now_str('%Y%m%d_%H%M%S')}"
            output_dir = paths.selfplay_dir / run_id
        baseline_dir = output_dir / "baseline"
        candidate_dir = output_dir / "candidate"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        candidate_dir.mkdir(parents=True, exist_ok=True)

        # Shared training config builder
        def _make_training_config(
            side_dir: Path,
            skill_dir: Path | None,
            role_skill_dirs: dict[str, Path] | None,
        ) -> TrainingConfig:
            return TrainingConfig(
                num_games=config.num_games,
                seed_start=config.seed_start,
                max_days=config.max_days,
                enable_sheriff=config.enable_sheriff,
                skill_dir=skill_dir,
                role_skill_dirs=role_skill_dirs,
                model=model,
                game_concurrency=config.game_concurrency,
                enable_mid_memory=False,  # No mid-memory during battle
                output_dir=side_dir,
                db_path=db_path,
            )

        baseline_cfg = _make_training_config(
            baseline_dir,
            config.baseline_skill_dir,
            config.baseline_role_skill_dirs,
        )
        candidate_cfg = _make_training_config(
            candidate_dir,
            config.candidate_skill_dir,
            config.candidate_role_skill_dirs,
        )

        # Run both sides concurrently
        baseline_result, candidate_result = await asyncio.gather(
            self.run_training_games(baseline_cfg),
            self.run_training_games(candidate_cfg),
        )

        # Compute summary
        summary = _compute_battle_summary(
            baseline_result.games,
            candidate_result.games,
            num_games=config.num_games,
            seed_start=config.seed_start,
        )
        significant = _is_significant(summary)

        # Persist battle summary
        _write_json_sync(output_dir / "battle_summary.json", {
            "summary": summary,
            "significant": significant,
        })

        return ABResult(
            baseline_results=baseline_result.games,
            candidate_results=candidate_result.games,
            summary=summary,
            significant=significant,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _run_single_training_game(
    *,
    seed: int,
    game_id: str,
    game_dir: Path,
    model: Any,
    max_days: int,
    enable_sheriff: bool,
    skill_dir: Path | None,
    role_skill_dirs: dict[str, Path] | None,
    enable_mid_memory: bool,
    db_path: Path | None,
    paths: Any | None = None,
) -> dict[str, Any]:
    """Run a single training game and return its result dict."""
    from agent.infrastructure.archive import AgentTraceRecorder, GameArchive
    from agent.infrastructure.decision_log import AgentDecisionRecorder
    from engine.config import STANDARD_12
    from engine.roles import assign_roles
    from storage.runtime import GamePersistence

    from agent.api.runtime import AgentRuntime

    started_at = beijing_now_iso()
    game_dir.mkdir(parents=True, exist_ok=True)

    # Assign roles with fixed seed
    roles = assign_roles(STANDARD_12, seed=seed)
    player_roles = {pid: r.value for pid, r in roles.items()}

    # Set up persistence
    persistence = GamePersistence(
        game_id=game_id,
        game_dir=game_dir,
        db_path=db_path,
    )

    # Create recorders (per-player trace recorders for detailed archives)
    decision_recorder: AgentDecisionRecorder = persistence.create_decision_recorder()
    trace_recorders: dict[int, AgentTraceRecorder] = {
        pid: AgentTraceRecorder() for pid in roles
    }

    # Create agents directly (no human players in training)
    agents: dict[int, AgentRuntime] = {}
    for player_id, role in sorted(roles.items()):
        if role_skill_dirs and role.value in role_skill_dirs:
            agent_skill_dir = role_skill_dirs[role.value]
        else:
            agent_skill_dir = skill_dir
        agents[player_id] = AgentRuntime(
            player_id=player_id,
            role=role,
            model=model,
            recorder=decision_recorder,
            trace_recorder=trace_recorders[player_id],
            game_id=game_id,
            skill_dir=agent_skill_dir,
            paths=paths,
        )

    # Create engine
    engine = create_engine(
        roles,
        agents,
        seed=seed,
        max_days=max_days,
        enable_sheriff=enable_sheriff,
        logger=persistence.create_event_logger(game_dir / "game_events.jsonl"),
    )

    # Run game
    game_error: str | None = None
    winner_str = "error"
    try:
        winner = await engine.run_until_finished()
        winner_str = winner.value if hasattr(winner, "value") else str(winner)
    except Exception as exc:
        _log.error("Training game %s failed: %s", game_id, exc, exc_info=True)
        game_error = str(exc)

    finished_at = beijing_now_iso()
    days = getattr(engine.state, "day", 0) or 0

    # Build merged archive from per-player trace recorders
    from agent.infrastructure.archive import DecisionArchive
    all_decisions: list[DecisionArchive] = []
    for recorder in trace_recorders.values():
        all_decisions.extend(recorder.snapshot())

    archive = GameArchive(
        game_id=game_id,
        seed=seed,
        config={"skill_dir": str(skill_dir) if skill_dir else None},
        player_roles=player_roles,
        winner=winner_str,
        started_at=started_at,
        finished_at=finished_at,
        public_events=[e.to_dict() for e in engine.logger.entries],
        decisions=all_decisions,
        final_state={"player_roles": player_roles, "winner": winner_str},
    )
    archive.write_json(game_dir / "archive.json")

    # Save to SQLite
    try:
        deaths = [
            {
                "player_id": d.player_id,
                "cause": d.cause.value if hasattr(d.cause, "value") else str(d.cause),
                "day": d.day,
            }
            for d in engine.state.deaths
        ]
        persistence.save_game_result(
            seed=seed,
            player_roles=player_roles,
            config=archive.config,
            winner=winner_str,
            started_at=started_at,
            finished_at=finished_at,
            total_rounds=days,
            public_events=[e.to_dict() for e in engine.logger.entries],
            final_state=archive.final_state,
            deaths=deaths,
        )
    except Exception:
        _log.warning("Failed to save training game to SQLite: %s", game_id, exc_info=True)

    # Mid-memory analysis (evidence pipeline)
    if enable_mid_memory and not game_error and winner_str != "error":
        try:
            from agent.learning.pipeline import run_evidence_pipeline
            evidence_result = await run_evidence_pipeline(
                game_dir,
                model=model,
                output_dir=game_dir / "learning",
            )
            persistence.save_experience_candidates(evidence_result.experience_candidates)
        except Exception as exc:
            _log.error("mid_memory_error for %s: %s", game_id, exc, exc_info=True)

    # Write meta.json for resume support
    _write_json_sync(game_dir / "meta.json", {
        "game_id": game_id,
        "seed": seed,
        "winner": winner_str,
        "days": days,
        "players": player_roles,
    })

    persistence.close()

    # Collect decision statistics
    decision_count = 0
    fallback_count = 0
    llm_error_count = 0
    for rec in decision_recorder.records:
        decision_count += 1
        source = getattr(rec, "source", "")
        if source == "fallback":
            fallback_count += 1
        elif source == "llm_error":
            llm_error_count += 1

    return {
        "game_id": game_id,
        "seed": seed,
        "winner": winner_str,
        "days": days,
        "player_roles": player_roles,
        "decision_count": decision_count,
        "fallback_count": fallback_count,
        "llm_error_count": llm_error_count,
        "started_at": started_at,
        "finished_at": finished_at,
        "error": game_error,
    }


def _compute_battle_summary(
    baseline_games: list[dict[str, Any]],
    candidate_games: list[dict[str, Any]],
    *,
    num_games: int,
    seed_start: int,
) -> dict[str, Any]:
    """Compute aggregate metrics for both sides of an A/B battle."""

    def _side_summary(games: list[dict[str, Any]]) -> dict[str, Any]:
        valid = [g for g in games if not g.get("error")]
        n = len(games)
        werewolf_wins = sum(
            1 for g in valid if "werewolf" in str(g.get("winner", "")).lower()
        )
        villager_wins = len(valid) - werewolf_wins
        total_decisions = sum(g.get("decision_count", 0) for g in valid)
        total_fallbacks = sum(g.get("fallback_count", 0) for g in valid)
        total_llm_errors = sum(g.get("llm_error_count", 0) for g in valid)
        return {
            "games": n,
            "valid": len(valid),
            "errors": n - len(valid),
            "werewolf_wins": werewolf_wins,
            "villager_wins": villager_wins,
            "werewolf_win_rate": werewolf_wins / len(valid) if valid else 0.0,
            "villager_win_rate": villager_wins / len(valid) if valid else 0.0,
            "avg_days": (
                sum(g.get("days", 0) for g in valid) / len(valid)
                if valid
                else 0.0
            ),
            "total_decisions": total_decisions,
            "fallback_rate": (
                total_fallbacks / total_decisions if total_decisions else 0.0
            ),
            "llm_error_rate": (
                total_llm_errors / total_decisions if total_decisions else 0.0
            ),
        }

    return {
        "num_games": num_games,
        "seed_start": seed_start,
        "seeds": list(range(seed_start, seed_start + num_games)),
        "baseline": _side_summary(baseline_games),
        "candidate": _side_summary(candidate_games),
    }


def _is_significant(summary: dict[str, Any]) -> bool:
    """Check if the candidate is meaningfully better than the baseline.

    Criteria (aligned with battle.py significance check):
    1. Both sides must have >= 70%% valid (non-errored) games.
    2. Candidate villager-side or werewolf-side win rate must improve
       by >= 10%% absolute over baseline.
    """
    baseline = summary.get("baseline", {})
    candidate = summary.get("candidate", {})

    # Reject if too many errors
    for side_name, side in [("baseline", baseline), ("candidate", candidate)]:
        total = side.get("games", 0)
        errors = side.get("errors", 0)
        if total > 0 and errors / total > 0.3:
            _log.warning(
                "Significance check failed: %s has %d/%d errored games (>30%%)",
                side_name,
                errors,
                total,
            )
            return False

    # Check win rate improvement on either side
    baseline_wwr = baseline.get("werewolf_win_rate", 0.0)
    candidate_wwr = candidate.get("werewolf_win_rate", 0.0)
    baseline_vwr = baseline.get("villager_win_rate", 0.0)
    candidate_vwr = candidate.get("villager_win_rate", 0.0)

    werewolf_improved = candidate_wwr >= baseline_wwr + 0.10
    villager_improved = candidate_vwr >= baseline_vwr + 0.10

    return werewolf_improved or villager_improved


def _write_json_sync(path: Path, data: Any) -> None:
    """Write JSON data to a file, creating parent directories as needed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        _log.warning("Failed to write %s", path, exc_info=True)
