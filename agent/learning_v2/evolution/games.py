"""Game runner — multi-game batch runner for agent evaluation and evolution.

Runs N games with configurable seeds, collects full archives,
generates per-game reviews, experiences, and a run summary.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.learning_v2.stats import new_role_accum, finalize_role_metrics
from agent.infrastructure.decision_log import AgentDecisionRecorder
from agent.infrastructure.llm import ModelAdapter
from agent.common import beijing_now_iso as _now, beijing_now_str, is_werewolf_win
from agent.common.paths import DEFAULT as DEFAULT_PATHS
from engine.config import GameConfig, STANDARD_12
from engine.engine import GameEngine
from engine.models import Role
from engine.roles import assign_roles

from agent.infrastructure.archive import AgentTraceRecorder, DecisionArchive, GameArchive
from agent.learning_v2.pipeline import run_evidence_pipeline
from agent.learning_v2.stats import calibrate_decisions, merge_calibration_reports
from agent.learning_v2.review import generate_enhanced_review
from agent.api.runtime import AgentRuntime
from agent.api.factory import load_llm_client
from storage.ids import artifact_game_id
from storage.runtime import GamePersistence, open_storage_connection
from agent.infrastructure.llm import (
    AsyncRateLimiter,
    default_rate_limiter_from_env,
    limit_model_adapter,
    rate_limit_model_adapter,
)

_log = logging.getLogger(__name__)

MAX_REVIEW_SCORE = 10.0


def _suppress_dependency_warning_noise() -> None:
    warnings.filterwarnings(
        "ignore",
        message=r"SelectableGroups dict interface is deprecated\. Use select\.",
        category=DeprecationWarning,
    )


@dataclass(slots=True)
class SelfPlayConfig:
    """Configuration for a selfplay run."""

    games: int
    seed_start: int = 1
    output_dir: Path = DEFAULT_PATHS.selfplay_dir
    agent_version: str = "agent"
    model_name: str | None = None
    max_days: int = 20
    enable_review: bool = True
    enable_mid_memory: bool = True
    enable_long_term_consolidation: bool = True
    consolidation_window: int = 5
    auto_apply_skill_proposals: bool = False
    enable_batch_dream: bool = False
    temperature: float = 0.2
    game_config: GameConfig = STANDARD_12
    skill_dir: Path | None = None
    game_concurrency: int = 1
    db_path: Path | None = None


@dataclass(slots=True)
class SelfPlayGameResult:
    """Result of a single selfplay game."""

    game_id: str
    seed: int
    winner: str
    days: int
    player_roles: dict[int, str]
    decision_count: int
    fallback_count: int
    policy_adjusted_count: int
    avg_confidence: float
    review_score: float | None
    output_dir: Path
    llm_error_count: int = 0
    confidence_calibration_error: float = 0.0
    confidence_calibration_count: int = 0
    confidence_buckets: dict = field(default_factory=dict)
    role_weighted_score: float = 0.0
    avg_speech_score: float = 0.0
    avg_vote_score: float = 0.0
    avg_skill_score: float = 0.0
    vote_accuracy: float = 0.0
    skill_accuracy: float = 0.0
    mistake_count: int = 0
    counterfactual_count: int = 0
    turning_point_count: int = 0
    information_score: float = 0.0
    cooperation_score: float = 0.0
    by_role: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        d = {
            "game_id": self.game_id,
            "seed": self.seed,
            "winner": self.winner,
            "days": self.days,
            "player_roles": {str(k): v for k, v in self.player_roles.items()},
            "decision_count": self.decision_count,
            "fallback_count": self.fallback_count,
            "llm_error_count": self.llm_error_count,
            "policy_adjusted_count": self.policy_adjusted_count,
            "avg_confidence": round(self.avg_confidence, 3),
            "confidence_calibration_error": round(self.confidence_calibration_error, 3),
            "confidence_calibration_count": self.confidence_calibration_count,
            "confidence_buckets": self.confidence_buckets or {},
            "review_score": round(self.review_score, 2) if self.review_score is not None else None,
            "avg_speech_score": round(self.avg_speech_score, 2),
            "role_weighted_score": round(self.role_weighted_score, 2),
            "avg_vote_score": round(self.avg_vote_score, 2),
            "avg_skill_score": round(self.avg_skill_score, 2),
            "vote_accuracy": round(self.vote_accuracy, 3),
            "skill_accuracy": round(self.skill_accuracy, 3),
            "output_dir": str(self.output_dir),
            "mistake_count": self.mistake_count,
            "counterfactual_count": self.counterfactual_count,
            "turning_point_count": self.turning_point_count,
            "information_score": round(self.information_score, 3),
            "cooperation_score": round(self.cooperation_score, 3),
            "by_role": self.by_role,
        }
        if self.error:
            d["error"] = self.error
        return d


@dataclass(slots=True)
class SelfPlayResult:
    """Aggregated result of a selfplay run."""

    config: SelfPlayConfig
    games: list[SelfPlayGameResult]
    run_id: str = ""
    started_at: str = ""
    finished_at: str = ""

    @property
    def summary(self) -> dict:
        n = len(self.games)
        if n == 0:
            return {"games": 0}

        normal = [g for g in self.games if not g.error]
        error_count = n - len(normal)

        werewolf_wins = sum(1 for g in normal if is_werewolf_win(g.winner))
        villager_wins = len(normal) - werewolf_wins
        total_decisions = sum(g.decision_count for g in self.games)
        total_fallbacks = sum(g.fallback_count for g in self.games)
        total_llm_errors = sum(g.llm_error_count for g in self.games)
        total_adjusted = sum(g.policy_adjusted_count for g in self.games)
        scores = [g.review_score for g in self.games if g.review_score is not None]
        role_weighted_scores = [g.role_weighted_score for g in self.games if g.review_score is not None and g.role_weighted_score is not None]
        reviewed = [g for g in self.games if g.review_score is not None]
        calibration = merge_calibration_reports([g.to_dict() for g in self.games])
        mistake_total = sum(g.mistake_count for g in self.games)

        return {
            "run_id": self.run_id,
            "games": n,
            "error_count": error_count,
            "werewolf_wins": werewolf_wins,
            "villager_wins": villager_wins,
            "werewolf_win_rate": round(werewolf_wins / len(normal), 3) if normal else 0.0,
            "villager_win_rate": round(villager_wins / len(normal), 3) if normal else 0.0,
            "avg_days": round(sum(g.days for g in self.games) / n, 2) if n else 0.0,
            "avg_decision_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
            "score_samples": [round(score, 3) for score in scores],
            "role_weighted_score": round(sum(role_weighted_scores) / len(role_weighted_scores), 2) if role_weighted_scores else 0.0,
            "role_weighted_score_samples": [round(score, 3) for score in role_weighted_scores],
            "avg_speech_score": round(sum(g.avg_speech_score for g in reviewed) / len(reviewed), 2) if reviewed else 0.0,
            "avg_vote_score": round(sum(g.avg_vote_score for g in reviewed) / len(reviewed), 2) if reviewed else 0.0,
            "avg_skill_score": round(sum(g.avg_skill_score for g in reviewed) / len(reviewed), 2) if reviewed else 0.0,
            "vote_accuracy": round(sum(g.vote_accuracy for g in reviewed) / len(reviewed), 3) if reviewed else 0.0,
            "skill_accuracy": round(sum(g.skill_accuracy for g in reviewed) / len(reviewed), 3) if reviewed else 0.0,
            "total_decisions": total_decisions,
            "fallback_count": total_fallbacks,
            "llm_error_count": total_llm_errors,
            "policy_adjusted_count": total_adjusted,
            "fallback_rate": round(total_fallbacks / total_decisions, 4) if total_decisions else 0.0,
            "llm_error_rate": round(total_llm_errors / total_decisions, 4) if total_decisions else 0.0,
            "policy_adjusted_rate": round(total_adjusted / total_decisions, 4) if total_decisions else 0.0,
            "avg_confidence": round(sum(g.avg_confidence for g in self.games) / n, 3) if n else 0.0,
            "confidence_calibration_error": round(calibration["confidence_calibration_error"], 3),
            "confidence_calibration_count": calibration["confidence_calibration_count"],
            "confidence_buckets": calibration["confidence_buckets"],
            "mistake_count": mistake_total,
            "counterfactual_count": sum(g.counterfactual_count for g in self.games),
            "turning_point_count": sum(g.turning_point_count for g in self.games),
            # Leaderboard fields — aggregated by aggregate_summaries in leaderboard.py
            "bad_case_count": mistake_total,
            "turning_point_quality": 0.0,
            "information_score": round(sum(g.information_score for g in reviewed) / len(reviewed), 3) if reviewed else 0.0,
            "cooperation_score": round(sum(g.cooperation_score for g in reviewed) / len(reviewed), 3) if reviewed else 0.0,
            "by_role": _aggregate_by_role(self.games),
            "game_results": [g.to_dict() for g in self.games],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def summary_markdown(self) -> str:
        s = self.summary
        lines = [
            f"# Selfplay Run: {self.run_id}",
            "",
            f"**Agent**: {self.config.agent_version}",
            f"**Games**: {s['games']}",
            f"**Seeds**: {self.config.seed_start}–{self.config.seed_start + s['games'] - 1}",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| 狼人胜率 | {s['werewolf_win_rate']:.1%} ({s['werewolf_wins']}/{s['games'] - s.get('error_count', 0)}) |",
            f"| 好人胜率 | {s['villager_win_rate']:.1%} ({s['villager_wins']}/{s['games'] - s.get('error_count', 0)}) |",
            f"| 失败局 | {s.get('error_count', 0)} |",
            f"| 平均天数 | {s['avg_days']} |",
            f"| 平均决策评分 | {s['avg_decision_score']} |",
            f"| Fallback 率 | {s['fallback_rate']:.1%} |",
            f"| LLM 错误率 | {s['llm_error_rate']:.1%} ({s['llm_error_count']}) |",
            f"| Policy 修正率 | {s['policy_adjusted_rate']:.1%} |",
            f"| 平均置信度 | {s['avg_confidence']:.1%} |",
            f"| 置信度校准误差 | {s['confidence_calibration_error']:.1%} ({s['confidence_calibration_count']} samples) |",
            "",
            "## Per-Game Results",
            "",
        ]
        lines.append("| Game | Seed | Winner | Days | Decisions | Fallback | LLM Error | Adjusted | Conf | Score |")
        lines.append("|------|------|--------|------|-----------|----------|-----------|----------|------|-------|")
        for g in self.games:
            desc = g.game_id
            score_str = f"{g.review_score:.1f}" if g.review_score is not None else "-"
            lines.append(
                f"| {desc} | {g.seed} | {g.winner} | {g.days} | "
                f"{g.decision_count} | {g.fallback_count} | {g.llm_error_count} | {g.policy_adjusted_count} | "
                f"{g.avg_confidence:.2f} | {score_str} |"
            )
        lines.append("")
        return "\n".join(lines)

    def write_summary(self, output_dir: Path) -> None:
        """Write summary.json and summary.md to the output directory."""
        output_dir.mkdir(parents=True, exist_ok=True)
        # Atomic write for summary.json
        json_path = output_dir / "summary.json"
        json_tmp = json_path.with_suffix(json_path.suffix + ".tmp")
        with open(json_tmp, "w", encoding="utf-8") as f:
            json.dump(self.summary, f, ensure_ascii=False, indent=2)
        os.replace(str(json_tmp), str(json_path))
        with open(output_dir / "summary.md", "w", encoding="utf-8") as f:
            f.write(self.summary_markdown())


async def run_selfplay(
    config: SelfPlayConfig,
    *,
    model: ModelAdapter | None = None,
    client_factory: Callable[[], ModelAdapter] | None = None,
    on_game_complete: "Callable[[int, SelfPlayGameResult], None] | None" = None,
    llm_semaphore: asyncio.Semaphore | None = None,
    llm_rate_limiter: AsyncRateLimiter | None = None,
    run_dir: Path | None = None,
) -> SelfPlayResult:
    """Run a multi-game selfplay session.

    Args:
        config: Selfplay configuration.
        model: Shared model adapter. If None, uses load_llm_client() once per run.
        client_factory: Optional callable that returns a ModelAdapter per game.
        on_game_complete: Optional callback ``(game_index, game_result)``
            invoked after each game finishes.  *game_index* is zero-based.
        run_dir: Optional existing run directory for resuming. If None, a new
            ``run_<timestamp>`` directory is created under ``config.output_dir``.
    """
    _suppress_dependency_warning_noise()
    if run_dir is not None:
        run_id = run_dir.name
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_id = f"run_{beijing_now_str('%Y%m%d_%H%M%S_%f')}"
        run_dir = config.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

    started_at = _now()

    # Open SQLite connection for the run (if db_path configured)
    run_conn = None
    if config.db_path is not None:
        run_conn = open_storage_connection(config.db_path)

    # Write config
    await _write_json(run_dir / "config.json", {
        "games": config.games,
        "seed_start": config.seed_start,
        "agent_version": config.agent_version,
        "model_name": config.model_name,
        "max_days": config.max_days,
        "temperature": config.temperature,
        "enable_review": config.enable_review,
        "enable_mid_memory": config.enable_mid_memory,
        "enable_long_term_consolidation": config.enable_long_term_consolidation,
        "enable_batch_dream": config.enable_batch_dream,
        "auto_apply_skill_proposals": config.auto_apply_skill_proposals,
        "skill_dir": str(config.skill_dir) if config.skill_dir else None,
        "game_concurrency": config.game_concurrency,
    })

    results: list[SelfPlayGameResult | None] = [None] * config.games
    _frozen_skill_dir = config.skill_dir
    llm_rate_limiter = llm_rate_limiter or default_rate_limiter_from_env()
    shared_model = model
    if shared_model is None and client_factory is None:
        shared_model = load_llm_client(
            model_name=config.model_name,
            temperature=config.temperature,
        )
    if shared_model is not None:
        shared_model = limit_model_adapter(shared_model, llm_semaphore)
        shared_model = rate_limit_model_adapter(shared_model, llm_rate_limiter)
    completion_lock = asyncio.Lock()

    async def _run_index(i: int) -> None:
        if config.skill_dir != _frozen_skill_dir:
            raise ValueError(f"skill_dir changed mid-run: {_frozen_skill_dir} -> {config.skill_dir}")
        # Skip already-completed games (resume after restart)
        game_id = f"game_{i + 1:03d}"
        existing_meta = run_dir / "games" / game_id / "meta.json"
        if existing_meta.exists():
            try:
                meta = json.loads(existing_meta.read_text(encoding="utf-8"))
                winner = meta.get("winner", "error")
                results[i] = SelfPlayGameResult(
                    game_id=game_id,
                    seed=config.seed_start + i,
                    winner=winner,
                    days=meta.get("days", 0),
                    player_roles=meta.get("players", {}),
                    decision_count=0,
                    fallback_count=0,
                    llm_error_count=0,
                    policy_adjusted_count=0,
                    avg_confidence=0.0,
                    review_score=None,
                    output_dir=run_dir / "games" / game_id,
                )
                if on_game_complete is not None:
                    try:
                        on_game_complete(i, results[i])
                    except Exception:
                        _log.debug("on_game_complete callback raised for cached game %s", results[i].game_id, exc_info=True)
                return
            except Exception:
                _log.warning("Corrupt meta.json for game %s, will re-run", game_id, exc_info=True)
        client = client_factory() if client_factory else shared_model
        if client is None:
            client = load_llm_client(
                model_name=config.model_name,
                temperature=config.temperature,
            )
            client = limit_model_adapter(client, llm_semaphore)
            client = rate_limit_model_adapter(client, llm_rate_limiter)
        elif client_factory is not None:
            client = limit_model_adapter(client, llm_semaphore)
            client = rate_limit_model_adapter(client, llm_rate_limiter)
        result = await _run_single_game(
            config=config,
            run_dir=run_dir,
            game_index=i,
            client=client,
            conn=run_conn,
        )

        async with completion_lock:
            results[i] = result
        if on_game_complete is not None:
            try:
                on_game_complete(i, result)
            except Exception:
                _log.warning("on_game_complete callback raised for game %s", result.game_id, exc_info=True)

    if config.games > 0:
        game_concurrency = max(1, min(config.game_concurrency, config.games))
        game_limiter = asyncio.Semaphore(game_concurrency)

        async def _limited_run(i: int) -> None:
            async with game_limiter:
                await _run_index(i)

        await asyncio.gather(*(_limited_run(i) for i in range(config.games)))

    completed_results = [r for r in results if r is not None]

    # Long-term consolidation — every N games, LLM reads mid-memories and updates skills
    if (
        config.enable_long_term_consolidation
        and config.enable_mid_memory
        and len(completed_results) >= config.consolidation_window
    ):
        batch_client = shared_model
        if batch_client is None:
            batch_client = limit_model_adapter(
                load_llm_client(
                    model_name=config.model_name,
                    temperature=config.temperature,
                ),
                llm_semaphore,
            )
            batch_client = rate_limit_model_adapter(batch_client, llm_rate_limiter)
        await _run_long_term_consolidation(
            run_dir=run_dir,
            model=batch_client,
            skill_dir=config.skill_dir,
            window=config.consolidation_window,
            auto_apply=config.auto_apply_skill_proposals,
        )

    selfplay_result = SelfPlayResult(
        config=config,
        games=completed_results,
        run_id=run_id,
        started_at=started_at,
        finished_at=_now(),
    )

    # Write summary
    selfplay_result.write_summary(run_dir)
    if run_conn is not None:
        run_conn.close()
    return selfplay_result


async def _run_single_game(
    *,
    config: SelfPlayConfig,
    run_dir: Path,
    game_index: int,
    client: ModelAdapter,
    conn=None,
) -> SelfPlayGameResult:
    """Run one selfplay game and write its artifacts."""
    seed = config.seed_start + game_index
    game_id = f"game_{game_index + 1:03d}"
    game_dir = run_dir / "games" / game_id
    game_dir.mkdir(parents=True, exist_ok=True)
    storage_game_id = (
        artifact_game_id(
            game_dir,
            root=_storage_namespace_root(run_dir, config),
            raw_game_id=game_id,
        )
        if conn is not None
        else game_id
    )
    persistence = GamePersistence(
        game_id=storage_game_id,
        source_game_id=game_id,
        game_dir=game_dir,
        conn=conn,
    )

    roles = assign_roles(config.game_config, seed=seed)
    player_roles = {pid: r.value for pid, r in roles.items()}

    trace_recorders: dict[int, AgentTraceRecorder] = {
        pid: AgentTraceRecorder() for pid in roles
    }
    decision_recorder = persistence.create_decision_recorder()
    agents = _create_agents(
        roles, client, decision_recorder, trace_recorders,
        game_id=game_id,
        skill_dir=config.skill_dir,
    )

    engine = GameEngine(
        roles, agents, config.game_config,
        logger=persistence.create_event_logger(game_dir / "game_events.jsonl"),
    )
    game_started_at = _now()
    game_error: str | None = None
    try:
        winner = await engine.run_until_finished()
    except Exception as exc:
        _log.error("game %s failed", game_id, exc_info=True)
        game_error = str(exc)
        winner = None

    if winner is not None:
        winner_str = winner.value if hasattr(winner, "value") else str(winner)
    else:
        winner_str = "error"

    # game_events.jsonl already written via streaming; decisions in archive.json

    all_decisions: list[DecisionArchive] = []
    for recorder in trace_recorders.values():
        all_decisions.extend(recorder.snapshot())
    _align_trace_indices(all_decisions, decision_recorder.records)

    merged_archive = GameArchive(
        game_id=game_id,
        seed=seed,
        config={
            "agent_version": config.agent_version,
            "skill_dir": str(config.skill_dir) if config.skill_dir else None,
        },
        player_roles=player_roles,
        winner=winner_str,
        started_at=game_started_at,
        finished_at=_now(),
        public_events=[e.to_dict() for e in engine.state.events],
        decisions=all_decisions,
        final_state={"player_roles": player_roles, "winner": winner_str},
    )
    merged_archive.write_json(game_dir / "archive.json")

    # Write game + player records to SQLite
    if persistence.has_db:
        deaths = [
            {"player_id": d.player_id, "cause": d.cause.value if hasattr(d.cause, "value") else str(d.cause), "day": d.day}
            for d in engine.state.deaths
        ]
        persistence.save_game_result(
            seed=seed,
            player_roles=player_roles,
            config=merged_archive.config,
            winner=winner_str,
            started_at=game_started_at,
            finished_at=_now(),
            total_rounds=getattr(engine.state, "day", 0) or 0,
            public_events=[e.to_dict() for e in engine.state.events],
            final_state=merged_archive.final_state,
            deaths=deaths,
        )

    fallback_count = 0
    llm_error_count = 0
    policy_adjusted_count = 0
    total_decisions = 0
    total_confidence = 0.0
    for rec in decision_recorder.records:
        total_decisions += 1
        source = getattr(rec, "source", "")
        if source == "fallback":
            fallback_count += 1
        elif source == "llm_error":
            llm_error_count += 1
        elif source == "policy_adjusted":
            policy_adjusted_count += 1
        total_confidence += getattr(rec, "confidence", 0.0) or 0.0

    avg_confidence = total_confidence / total_decisions if total_decisions else 0.0
    calibration = calibrate_decisions(decision_recorder.records, roles)

    review_score = None
    review_report = None
    avg_speech_score = 0.0
    avg_vote_score = 0.0
    avg_skill_score = 0.0
    vote_accuracy = 0.0
    skill_accuracy = 0.0
    mistake_count = 0
    counterfactual_count = 0
    turning_point_count = 0
    information_score = 0.0
    cooperation_score = 0.0
    role_weighted_score = 0.0
    by_role: dict[str, dict[str, float | int]] = {}
    agent_decisions = _collect_decisions(decision_recorder)

    if config.enable_review and not game_error and winner is not None:
        review_report = generate_enhanced_review(
            game_log={"entries": [e.to_dict() for e in engine.logger.entries]},
            agent_decisions=agent_decisions,
            roles=roles,
            winner_team=winner.value if hasattr(winner, "value") else winner,
            game_id=game_id,
        )
        player_scores = list(review_report.player_scores.values())
        denominator = max(len(player_scores), 1)
        review_score = sum(s.total_score for s in player_scores) / denominator
        avg_speech_score = sum(s.speech_score for s in player_scores) / denominator
        avg_vote_score = sum(s.vote_score for s in player_scores) / denominator
        avg_skill_score = sum(s.skill_score for s in player_scores) / denominator
        vote_accuracy = avg_vote_score / MAX_REVIEW_SCORE
        skill_accuracy = avg_skill_score / MAX_REVIEW_SCORE
        mistake_count = len(review_report.mistakes)
        counterfactual_count = len(review_report.counterfactuals)
        turning_point_count = len(review_report.key_turning_points)
        information_score = sum(s.information_score for s in player_scores) / denominator
        cooperation_score = sum(s.cooperation_score for s in player_scores) / denominator
        role_weighted_score = sum(s.role_weighted_score for s in player_scores) / denominator
        by_role = _compute_by_role_metrics(
            review_report=review_report,
            decision_records=decision_recorder.records,
            roles=roles,
        )
        # review.json is derivable — skip file write

    # Evidence candidates are the new mid-term memory artifact; legacy
    # GameAnalysis stays available for the current long-term consolidator.
    if config.enable_mid_memory and not game_error and winner is not None:
        try:
            evidence_result = await run_evidence_pipeline(
                game_dir,
                model=client,
                output_dir=game_dir / "learning_v2",
            )
            persistence.save_experience_candidates(evidence_result.experience_candidates)
        except Exception as exc:
            _log.error("learning_v2_error for %s: %s", game_id, exc, exc_info=True)

    if config.enable_mid_memory and review_report is not None:
        try:
            from agent.learning_v2.game_analysis import analyze_game, write_game_analysis

            game_analysis = await analyze_game(
                model=client,
                game_id=game_id,
                review=review_report,
                agent_decisions=agent_decisions,
                roles=roles,
                winner_team=winner_str,
            )
            write_game_analysis(
                game_analysis,
                output_dir=game_dir / "mid_memory",
            )
        except Exception as exc:
            _log.error("mid_memory_error for %s: %s", game_id, exc, exc_info=True)

    await _write_json(game_dir / "meta.json", {
        "game_id": game_id,
        "seed": seed,
        "agent_version": config.agent_version,
        "winner": winner_str,
        "days": getattr(engine.state, "day", 0) or 0,
        "players": player_roles,
    })
    persistence.close()

    return SelfPlayGameResult(
        game_id=game_id,
        seed=seed,
        winner=winner_str,
        days=getattr(engine.state, "day", 0) or 0,
        player_roles=player_roles,
        decision_count=total_decisions,
        fallback_count=fallback_count,
        llm_error_count=llm_error_count,
        policy_adjusted_count=policy_adjusted_count,
        avg_confidence=avg_confidence,
        confidence_calibration_error=calibration["confidence_calibration_error"],
        confidence_calibration_count=calibration["confidence_calibration_count"],
        confidence_buckets=calibration["confidence_buckets"],
        review_score=review_score,
        output_dir=game_dir,
        role_weighted_score=role_weighted_score,
        avg_speech_score=avg_speech_score,
        avg_vote_score=avg_vote_score,
        avg_skill_score=avg_skill_score,
        vote_accuracy=vote_accuracy,
        skill_accuracy=skill_accuracy,
        mistake_count=mistake_count,
        counterfactual_count=counterfactual_count,
        turning_point_count=turning_point_count,
        information_score=information_score,
        cooperation_score=cooperation_score,
        by_role=by_role,
        error=game_error,
    )


async def _run_long_term_consolidation(
    *,
    run_dir: Path,
    model: ModelAdapter,
    skill_dir: Path | None,
    window: int,
    auto_apply: bool,
) -> None:
    """Run long-term consolidation for all roles using recent mid-term memories."""
    from agent.learning_v2.game_analysis import GameAnalysis, load_game_analysis
    from agent.learning_v2.evolution.consolidation import (
        consolidate_from_mid_memories,
        write_consolidation,
    )

    # Collect mid-memory analyses from game directories
    mid_memories: list[GameAnalysis] = []
    for game_dir in sorted((run_dir / "games").glob("game*")):
        analysis_path = game_dir / "mid_memory"
        for json_file in sorted(analysis_path.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                analysis = load_game_analysis(data.get("game_id", ""), mid_memory_dir=analysis_path)
                if analysis is not None:
                    mid_memories.append(analysis)
            except Exception:
                _log.warning("Failed to load analysis from %s", json_file, exc_info=True)
                continue

    if len(mid_memories) < window:
        return

    # Take the most recent N
    recent = mid_memories[-window:]

    # Consolidate per role
    roles_seen: set[str] = set()
    for m in recent:
        for role_str in m.roles.values():
            roles_seen.add(role_str)

    for role_str in sorted(roles_seen):
        try:
            role = Role(role_str)
        except ValueError:
            continue
        consolidation = await consolidate_from_mid_memories(
            model=model,
            mid_memories=recent,
            role=role,
            skill_root=skill_dir,
        )
        write_consolidation(
            consolidation,
            output_dir=run_dir / "consolidations" / role_str,
        )


def _create_agents(
    roles: dict[int, Role],
    client: ModelAdapter,
    decision_recorder: AgentDecisionRecorder,
    trace_recorders: dict[int, AgentTraceRecorder],
    game_id: str | None = None,
    skill_dir: Path | None = None,
) -> dict[int, AgentRuntime]:
    """Create a full set of AgentRuntime with trace recorders."""
    agents: dict[int, AgentRuntime] = {}
    for player_id, role in sorted(roles.items()):
        agent = AgentRuntime(
            player_id=player_id,
            role=role,
            model=client,
            recorder=decision_recorder,
            trace_recorder=trace_recorders[player_id],
            game_id=game_id,
            skill_dir=skill_dir,
        )
        agents[player_id] = agent
    return agents


def _collect_decisions(recorder: AgentDecisionRecorder) -> dict[int, list[dict]]:
    """Group decision records by player_id."""
    decisions: dict[int, list[dict]] = {}
    for rec in recorder.records:
        pid = getattr(rec, "player_id", None)
        if pid is not None:
            decisions.setdefault(pid, []).append(rec.to_dict() if hasattr(rec, "to_dict") else {})
    return decisions


def _align_trace_indices(
    traces: list[DecisionArchive],
    records: list[Any],
) -> None:
    """Align heavy trace order with the global lightweight decision log."""
    order_by_id: dict[str, int] = {}
    for index, record in enumerate(records, start=1):
        decision_id = getattr(record, "decision_id", "")
        if decision_id:
            order_by_id[str(decision_id)] = index
    next_index = len(order_by_id) + 1
    for trace in traces:
        index = order_by_id.get(trace.decision_id)
        if index is None:
            index = next_index
            next_index += 1
        trace.index = index
    traces.sort(key=lambda trace: trace.index)


def _compute_by_role_metrics(
    *,
    review_report: Any,
    decision_records: list[Any],
    roles: dict[int, Role],
) -> dict[str, dict[str, float | int]]:
    """Aggregate reviewed player and decision metrics by role for one game."""
    result: dict[str, dict[str, float | int]] = {}
    for pid, role in roles.items():
        role_name = role.value
        state = result.setdefault(role_name, new_role_accum())
        player_review = review_report.player_scores.get(pid)
        state["players"] = int(state["players"]) + 1
        if player_review is not None:
            if player_review.outcome == "win":
                state["wins"] = int(state["wins"]) + 1
            else:
                state["losses"] = int(state["losses"]) + 1
            state["total_score_sum"] = float(state["total_score_sum"]) + player_review.total_score
            state["role_weighted_score_sum"] = (
                float(state["role_weighted_score_sum"]) + player_review.role_weighted_score
            )
            state["speech_score_sum"] = float(state["speech_score_sum"]) + player_review.speech_score
            state["vote_score_sum"] = float(state["vote_score_sum"]) + player_review.vote_score
            state["skill_score_sum"] = float(state["skill_score_sum"]) + player_review.skill_score
            state["information_score_sum"] = (
                float(state["information_score_sum"]) + player_review.information_score
            )
            state["cooperation_score_sum"] = (
                float(state["cooperation_score_sum"]) + player_review.cooperation_score
            )

    for rec in decision_records:
        pid = getattr(rec, "player_id", None)
        if pid is None or pid not in roles:
            continue
        role_name = roles[pid].value
        state = result.setdefault(role_name, new_role_accum())
        state["decision_count"] = int(state["decision_count"]) + 1
        source = getattr(rec, "source", "")
        if source == "fallback":
            state["fallback_count"] = int(state["fallback_count"]) + 1
        elif source == "llm_error":
            state["llm_error_count"] = int(state["llm_error_count"]) + 1
        elif source == "policy_adjusted":
            state["policy_adjusted_count"] = int(state["policy_adjusted_count"]) + 1

    for mistake in getattr(review_report, "mistakes", []):
        role_name = getattr(mistake, "role", "")
        if role_name not in result:
            continue
        result[role_name]["bad_case_count"] = int(result[role_name]["bad_case_count"]) + 1

    return {
        role_name: finalize_role_metrics(state)
        for role_name, state in sorted(result.items())
    }


def _aggregate_by_role(games: list[SelfPlayGameResult]) -> dict[str, dict[str, float | int]]:
    """Aggregate per-game role metrics across a selfplay run."""
    accum: dict[str, dict[str, float | int]] = {}
    for game in games:
        for role_name, metrics in (game.by_role or {}).items():
            state = accum.setdefault(role_name, new_role_accum())
            players = int(metrics.get("players", 0))
            state["players"] = int(state["players"]) + players
            state["wins"] = int(state["wins"]) + int(metrics.get("wins", 0))
            state["losses"] = int(state["losses"]) + int(metrics.get("losses", 0))
            state["decision_count"] = (
                int(state["decision_count"]) + int(metrics.get("decision_count", 0))
            )
            state["fallback_count"] = (
                int(state["fallback_count"]) + int(metrics.get("fallback_count", 0))
            )
            state["llm_error_count"] = (
                int(state["llm_error_count"]) + int(metrics.get("llm_error_count", 0))
            )
            state["policy_adjusted_count"] = (
                int(state["policy_adjusted_count"]) + int(metrics.get("policy_adjusted_count", 0))
            )
            state["bad_case_count"] = (
                int(state["bad_case_count"]) + int(metrics.get("bad_case_count", 0))
            )
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
    return {
        role_name: finalize_role_metrics(state)
        for role_name, state in sorted(accum.items())
    }


def _storage_namespace_root(run_dir: Path, config: SelfPlayConfig) -> Path | None:
    for root in (DEFAULT_PATHS.runs_dir, config.output_dir.parent):
        try:
            run_dir.resolve().relative_to(root.resolve())
            return root
        except ValueError:
            continue
    return None


def _write_json_sync(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(path))


async def _write_json(path: Path, data: Any) -> None:
    await asyncio.to_thread(_write_json_sync, path, data)


