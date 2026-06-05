"""Evaluation batch runner.

Runs batches of games for benchmarking model_id or single-role version_id
comparisons. Each game uses run_type=evaluation_batch with learning_eligible=False.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.common import beijing_now_iso
from agent.common.run_policy import RunType
from agent.evaluation.config import EvaluationBatchConfig
from agent.evaluation.fairness import (
    FairnessResult,
    compute_rankable,
    validate_model_comparison,
    validate_role_version_comparison,
)
from agent.evaluation.leaderboard import (
    compute_model_leaderboard_entry,
    compute_role_version_leaderboard_entry,
    persist_leaderboard_entry,
)
from agent.evaluation.metrics import BatchScoreSummary, aggregate_batch_scores, PlayerScore

_log = logging.getLogger(__name__)


@dataclass
class EvaluationGameResult:
    """Result of a single evaluation game."""

    game_id: str
    seed: int
    winner: str
    days: int
    player_roles: dict[int, str]
    player_scores: list[PlayerScore] = field(default_factory=list)
    error: str | None = None


@dataclass
class EvaluationBatchResult:
    """Result of an entire evaluation batch."""

    batch_id: str
    config: EvaluationBatchConfig
    games: list[EvaluationGameResult] = field(default_factory=list)
    score_summary: BatchScoreSummary | None = None
    fairness: FairnessResult | None = None
    rankable: bool = False
    rankable_reason: str = ""
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "config": self.config.to_dict(),
            "game_count": len(self.games),
            "completed": sum(1 for g in self.games if not g.error),
            "errored": sum(1 for g in self.games if g.error),
            "rankable": self.rankable,
            "rankable_reason": self.rankable_reason,
            "fairness": self.fairness.__dict__ if self.fairness else None,
            "score_summary": _summary_to_dict(self.score_summary) if self.score_summary else None,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class EvaluationBatchRunner:
    """Runner for evaluation batches.

    Each game runs with:
    - run_type = evaluation_batch
    - learning_eligible = False
    - temperature = 1.0 (fixed)
    """

    def __init__(self, *, paths: Any | None = None, registry: Any | None = None) -> None:
        self._paths = paths
        self._registry = registry

    def _resolve_paths(self) -> Any:
        if self._paths is not None:
            return self._paths
        from agent.common.paths import DEFAULT as DEFAULT_PATHS
        return DEFAULT_PATHS

    async def run_batch(
        self,
        config: EvaluationBatchConfig,
        *,
        on_game_complete: Callable[[int, EvaluationGameResult], None] | None = None,
    ) -> EvaluationBatchResult:
        """Run an evaluation batch and return results."""
        from agent.api.factory import load_llm_client
        from agent.learning.review.service import ReviewService
        from agent.learning.evolution.config import build_composite_skill_dir
        from agent.learning.evolution.models import SkillVersionConfig

        paths = self._resolve_paths()
        started_at = beijing_now_iso()
        batch_id = config.batch_id or _generate_batch_id()
        config.batch_id = batch_id

        # Output directory
        run_dir = paths.runs_dir / "evaluation_batches" / batch_id
        run_dir.mkdir(parents=True, exist_ok=True)

        registry, owns_registry = _open_registry(paths, self._registry)
        skill_dir: Path | None = None
        config.role_version_config = _resolve_role_version_config(config, registry)
        if config.role_version_config:
            skill_dir = build_composite_skill_dir(
                registry,
                SkillVersionConfig(
                    name=f"eval-{batch_id}",
                    created_at=started_at,
                    role_versions=dict(config.role_version_config),
                    notes=["evaluation batch resolved role versions"],
                ),
            )

        model = load_llm_client(
            model_name=config.model_id or None,
            temperature=config.temperature,
        )
        review_service = ReviewService()

        db_path = paths.battle_db_path
        results: list[EvaluationGameResult | None] = [None] * config.game_count

        async def _run_index(i: int) -> None:
            seed = i  # Sequential seeds for reproducibility
            artifact_game_id = f"eval_{i + 1:03d}"
            game_id = f"evaluation::{batch_id}::games::{artifact_game_id}"
            game_dir = run_dir / "games" / artifact_game_id
            game_dir.mkdir(parents=True, exist_ok=True)

            result = await _run_single_eval_game(
                seed=seed,
                game_id=game_id,
                game_dir=game_dir,
                model=model,
                max_days=config.max_days,
                db_path=db_path,
                paths=paths,
                review_service=review_service,
                config=config,
                skill_dir=skill_dir,
            )
            results[i] = result
            if on_game_complete is not None:
                try:
                    on_game_complete(i, result)
                except Exception:
                    _log.debug("on_game_complete callback raised", exc_info=True)

        # Run games with concurrency
        concurrency = max(1, min(3, config.game_count))
        semaphore = asyncio.Semaphore(concurrency)

        async def _limited(i: int) -> None:
            async with semaphore:
                await _run_index(i)

        if config.game_count > 0:
            await asyncio.gather(*(_limited(i) for i in range(config.game_count)))

        completed_results = [r for r in results if r is not None]
        finished_at = beijing_now_iso()

        # Aggregate scores
        all_scores = []
        for r in completed_results:
            all_scores.extend(r.player_scores)

        score_summary = aggregate_batch_scores(all_scores, batch_id=batch_id)

        fairness = _compute_group_fairness(paths, config, batch_id)

        # Compute rankable
        valid_count = sum(1 for r in completed_results if not r.error)
        valid_rate = valid_count / config.game_count if config.game_count > 0 else 0.0
        rankable, rankable_reason = compute_rankable(
            mode=config.mode,
            paired_seed=config.paired_seed,
            game_count=config.game_count,
            valid_game_rate=valid_rate,
            is_fair=fairness.is_fair,
        )

        batch_result = EvaluationBatchResult(
            batch_id=batch_id,
            config=config,
            games=[r for r in completed_results],
            score_summary=score_summary,
            fairness=fairness,
            rankable=rankable,
            rankable_reason=rankable_reason,
            started_at=started_at,
            finished_at=finished_at,
        )

        # Persist summary
        _write_json(run_dir / "summary.json", batch_result.to_dict())

        # Persist to DB
        try:
            _persist_batch(paths, batch_result)
        except Exception:
            _log.warning("Failed to persist evaluation batch to DB", exc_info=True)

        # Persist leaderboard entry
        try:
            _persist_leaderboard(paths, batch_result)
        except Exception:
            _log.warning("Failed to persist leaderboard entry", exc_info=True)

        if skill_dir is not None:
            shutil.rmtree(skill_dir, ignore_errors=True)
        if owns_registry and hasattr(registry, "close"):
            registry.close()
        return batch_result


async def _run_single_eval_game(
    *,
    seed: int,
    game_id: str,
    game_dir: Path,
    model: Any,
    max_days: int,
    db_path: Path,
    paths: Any,
    review_service: Any,
    config: EvaluationBatchConfig,
    skill_dir: Path | None = None,
) -> EvaluationGameResult:
    """Run a single evaluation game."""
    from agent.common.run_policy import policy_for_run_type
    from agent.infrastructure.decision_log import AgentDecisionRecorder
    from engine.config import STANDARD_12
    from engine.roles import assign_roles
    from storage.runtime import GamePersistence
    from agent.api.runtime import AgentRuntime
    from agent.runner.shared import create_engine

    started_at = beijing_now_iso()
    game_dir.mkdir(parents=True, exist_ok=True)

    # Assign roles
    roles = assign_roles(STANDARD_12, seed=seed)
    player_roles = {pid: r.value for pid, r in roles.items()}
    role_version_ids = {
        pid: config.role_version_config.get(role.value, "")
        for pid, role in roles.items()
        if config.role_version_config.get(role.value)
    }

    # Set up persistence with evaluation_batch policy
    run_policy = policy_for_run_type(RunType.EVALUATION_BATCH)
    persistence = GamePersistence(
        game_id=game_id,
        game_dir=game_dir,
        db_path=db_path,
        run_policy=run_policy,
        run_metadata={
            "mode": config.mode,
            "model_id": config.model_id,
            "model_config_hash": config.model_config_hash,
            "ruleset_version": config.ruleset_version,
            "evaluation_set_id": config.evaluation_set_id,
            "seed_set_id": config.seed_set_id,
            "comparison_group_id": config.comparison_group_id,
            "batch_id": config.batch_id,
        },
    )

    decision_recorder: AgentDecisionRecorder = persistence.create_decision_recorder()

    # Create agents
    agents: dict[int, AgentRuntime] = {}
    for player_id, role in sorted(roles.items()):
        agents[player_id] = AgentRuntime(
            player_id=player_id,
            role=role,
            model=model,
            recorder=decision_recorder,
            game_id=game_id,
            skill_dir=skill_dir,
            paths=paths,
        )

    # Create engine
    engine = create_engine(
        roles,
        agents,
        seed=seed,
        max_days=max_days,
        enable_sheriff=True,
        logger=persistence.create_event_logger(game_dir / "game_events.jsonl"),
    )

    # Run game
    game_error: str | None = None
    winner_str = "error"
    try:
        winner = await engine.run_until_finished()
        winner_str = winner.value if hasattr(winner, "value") else str(winner)
    except Exception as exc:
        _log.error("Evaluation game %s failed: %s", game_id, exc, exc_info=True)
        game_error = str(exc)

    days = getattr(engine.state, "day", 0) or 0

    # Save game result
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
            winner=winner_str,
            started_at=started_at,
            finished_at=beijing_now_iso(),
            total_rounds=days,
            public_events=[e.to_dict() for e in engine.logger.entries],
            final_state={"player_roles": player_roles, "winner": winner_str},
            deaths=deaths,
            role_version_ids=role_version_ids,
        )
    except Exception:
        _log.warning("Failed to save evaluation game to SQLite", exc_info=True)

    # Collect decisions and run review
    decisions = [
        {**record.to_dict(), "index": index}
        for index, record in enumerate(decision_recorder.records, start=1)
    ]
    events = [e.to_dict() for e in engine.logger.entries]

    player_scores: list[PlayerScore] = []
    if not game_error and winner_str != "error":
        try:
            review_result = review_service.review_game(
                game_id=game_id,
                events=events,
                decisions=decisions,
                player_roles=player_roles,
                winner=winner_str,
            )
            # Convert evaluations to PlayerScore
            for pe in review_result.player_evaluations:
                from agent.evaluation.metrics import compute_role_score
                ps = PlayerScore(
                    player_id=pe.player_seat,
                    role=pe.role,
                    speech_score=pe.speech_score or 0.0,
                    vote_score=pe.vote_score or 0.0,
                    skill_score=pe.skill_score or 0.0,
                    logic_score=getattr(pe, "information_score", 0.0) or 0.0,
                    team_score=getattr(pe, "cooperation_score", 0.0) or 0.0,
                    risk_penalty=getattr(pe, "risk_penalty", 0.0) or 0.0,
                )
                ps.role_score = compute_role_score(
                    speech_score=ps.speech_score,
                    vote_score=ps.vote_score,
                    skill_score=ps.skill_score,
                    logic_score=ps.logic_score,
                    team_score=ps.team_score,
                    risk_penalty=ps.risk_penalty,
                    skill_applicable=ps.skill_applicable,
                )
                player_scores.append(ps)

            # Persist review to DB
            if persistence.conn:
                ReviewService.persist_to_db(persistence.conn, review_result)
        except Exception:
            _log.warning("Review failed for %s", game_id, exc_info=True)

    persistence.close()

    return EvaluationGameResult(
        game_id=game_id,
        seed=seed,
        winner=winner_str,
        days=days,
        player_roles=player_roles,
        player_scores=player_scores,
        error=game_error,
    )


def _generate_batch_id() -> str:
    from agent.common.time import beijing_now_str
    return f"batch_{beijing_now_str('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _open_registry(paths: Any, registry: Any | None) -> tuple[Any, bool]:
    if registry is not None:
        return registry, False
    from agent.learning.evolution.registry import VersionRegistry
    return VersionRegistry(paths.registry_dir), True


def _resolve_role_version_config(
    config: EvaluationBatchConfig,
    registry: Any,
) -> dict[str, str]:
    """Resolve the concrete role-version snapshot used by this batch."""
    if config.role_version_config:
        resolved = dict(config.role_version_config)
    else:
        from agent.learning.evolution.config import build_baseline_config
        resolved = dict(build_baseline_config(registry).role_versions)

    if config.comparison_type == "role_version":
        if not config.target_role or not config.target_version_id:
            raise ValueError("role_version evaluation requires target_role and target_version_id")
        resolved[config.target_role] = config.target_version_id
    return resolved


def _compute_group_fairness(
    paths: Any,
    config: EvaluationBatchConfig,
    batch_id: str,
) -> FairnessResult:
    if not config.comparison_group_id:
        return FairnessResult(False, "comparison_group_id required")

    batches = _load_comparison_group(paths, config.comparison_group_id, exclude_batch_id=batch_id)
    current = config.to_dict()
    current["batch_id"] = batch_id
    batches.append(current)

    if config.comparison_type == "role_version":
        if not config.target_role:
            return FairnessResult(False, "target_role required")
        return validate_role_version_comparison(batches, config.target_role)
    return validate_model_comparison(batches)


def _load_comparison_group(
    paths: Any,
    comparison_group_id: str,
    *,
    exclude_batch_id: str,
) -> list[dict[str, Any]]:
    from storage.schema import get_connection

    conn = get_connection(paths.battle_db_path)
    try:
        rows = conn.execute(
            "SELECT id, comparison_group_id, comparison_type, mode, model_id, "
            "model_config_hash, target_role, target_version_id, role_version_config, "
            "game_count, evaluation_set_id, seed_set_id, max_days, player_count, "
            "ruleset_version "
            "FROM evaluation_batches WHERE comparison_group_id = ? AND id != ?",
            (comparison_group_id, exclude_batch_id),
        ).fetchall()
    finally:
        conn.close()

    result: list[dict[str, Any]] = []
    for row in rows:
        role_version_config = {}
        try:
            role_version_config = json.loads(row["role_version_config"] or "{}")
        except json.JSONDecodeError:
            role_version_config = {}
        result.append({
            "batch_id": row["id"],
            "comparison_group_id": row["comparison_group_id"],
            "comparison_type": row["comparison_type"],
            "mode": row["mode"],
            "model_id": row["model_id"],
            "model_config_hash": row["model_config_hash"],
            "target_role": row["target_role"],
            "target_version_id": row["target_version_id"],
            "role_version_config": role_version_config,
            "game_count": row["game_count"],
            "evaluation_set_id": row["evaluation_set_id"],
            "seed_set_id": row["seed_set_id"],
            "max_days": row["max_days"],
            "player_count": row["player_count"],
            "ruleset_version": row["ruleset_version"],
        })
    return result


def _persist_batch(paths: Any, result: EvaluationBatchResult) -> None:
    """Persist evaluation batch to the evaluation_batches table."""
    from storage.schema import get_connection
    import json

    conn = get_connection(paths.battle_db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO evaluation_batches "
            "(id, comparison_group_id, comparison_type, mode, model_id, model_config_hash, "
            "target_role, target_version_id, role_version_config, game_count, "
            "evaluation_set_id, seed_set_id, max_days, player_count, ruleset_version, "
            "rankable, summary, started_at, finished_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
            (
                result.batch_id,
                result.config.comparison_group_id,
                result.config.comparison_type,
                result.config.mode,
                result.config.model_id,
                result.config.model_config_hash,
                result.config.target_role,
                result.config.target_version_id,
                json.dumps(result.config.role_version_config, ensure_ascii=False),
                result.config.game_count,
                result.config.evaluation_set_id,
                result.config.seed_set_id,
                result.config.max_days,
                result.config.player_count,
                result.config.ruleset_version,
                1 if result.rankable else 0,
                json.dumps(result.to_dict(), ensure_ascii=False),
                result.started_at,
                result.finished_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _persist_leaderboard(paths: Any, result: EvaluationBatchResult) -> None:
    """Compute and persist a leaderboard entry for the completed batch."""
    from storage.schema import get_connection

    cfg = result.config
    game_count = len(result.games)

    if cfg.comparison_type == "role_version":
        if not cfg.target_role or not cfg.target_version_id:
            _log.debug("Skipping leaderboard: role_version batch missing target_role/version_id")
            return
        entry = compute_role_version_leaderboard_entry(
            batch_id=result.batch_id,
            target_role=cfg.target_role,
            target_version_id=cfg.target_version_id,
            model_id=cfg.model_id,
            evaluation_set_id=cfg.evaluation_set_id,
            seed_set_id=cfg.seed_set_id,
            score_summary=result.score_summary,
            rankable=result.rankable,
            game_count=game_count,
        )
    else:
        entry = compute_model_leaderboard_entry(
            batch_id=result.batch_id,
            model_id=cfg.model_id,
            model_config_hash=cfg.model_config_hash,
            evaluation_set_id=cfg.evaluation_set_id,
            seed_set_id=cfg.seed_set_id,
            score_summary=result.score_summary,
            rankable=result.rankable,
            game_count=game_count,
        )

    conn = get_connection(paths.battle_db_path)
    try:
        persist_leaderboard_entry(conn, entry)
    finally:
        conn.close()


def _summary_to_dict(summary: BatchScoreSummary) -> dict[str, Any]:
    return {
        "batch_id": summary.batch_id,
        "game_count": summary.game_count,
        "avg_role_score": round(summary.avg_role_score, 4),
        "by_role_category": {k: round(v, 4) for k, v in summary.by_role_category.items()},
        "avg_speech_score": round(summary.avg_speech_score, 4),
        "avg_vote_score": round(summary.avg_vote_score, 4),
        "avg_skill_score": round(summary.avg_skill_score, 4),
        "avg_logic_score": round(summary.avg_logic_score, 4),
        "avg_team_score": round(summary.avg_team_score, 4),
        "avg_risk_penalty": round(summary.avg_risk_penalty, 4),
        "strength_score": round(summary.strength_score, 4),
    }
