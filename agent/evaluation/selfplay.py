"""Selfplay — multi-game batch runner for agent evaluation.

Runs N games with configurable seeds, collects full archives,
generates per-game reviews, experiences, and a run summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.observability.decision_log import AgentDecisionRecorder
from agent.runtime.model import ModelAdapter
from engine.config import GameConfig, STANDARD_12
from engine.engine import GameEngine
from engine.models import Role
from engine.roles import assign_roles

from agent.observability.archive import AgentTraceRecorder, DecisionArchive, GameArchive
from agent.cognition.dream import dream_for_role, write_dream_report
from agent.cognition.experience import extract_experiences, write_game_experiences
from agent.cognition.long_memory import consolidate_role_memory, write_memory_candidate, write_role_memory
from agent.cognition.skill_evolution import (
    apply_skill_proposals,
    proposals_from_dream,
    write_skill_proposals,
)
from agent.evaluation.confidence_calibration import calibrate_decisions, merge_calibration_reports
from agent.evaluation.review_enhanced import generate_enhanced_review
from agent.runtime.agent import LLMPlayerAgent
from agent.runtime.factory import load_llm_client
from agent.skill_system.router import configure_skill_root


@dataclass(slots=True)
class SelfPlayConfig:
    """Configuration for a selfplay run."""

    games: int
    seed_start: int = 1
    output_dir: Path = Path("runs/selfplay")
    agent_version: str = "agent"
    model_name: str | None = None
    max_days: int = 20
    enable_review: bool = True
    enable_experience: bool = True
    enable_dream: bool = False
    enable_batch_dream: bool = False
    enable_skill_proposals: bool = True
    auto_apply_skill_proposals: bool = False
    temperature: float = 0.2
    game_config: GameConfig = STANDARD_12
    skill_dir: Path | None = None


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

        werewolf_wins = sum(1 for g in normal if _is_werewolf_winner(g.winner))
        villager_wins = len(normal) - werewolf_wins
        total_decisions = sum(g.decision_count for g in self.games)
        total_fallbacks = sum(g.fallback_count for g in self.games)
        total_adjusted = sum(g.policy_adjusted_count for g in self.games)
        scores = [g.review_score for g in self.games if g.review_score is not None]
        role_weighted_scores = [g.role_weighted_score for g in self.games if g.review_score is not None]
        reviewed = [g for g in self.games if g.review_score is not None]
        calibration = merge_calibration_reports([g.to_dict() for g in self.games])

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
            "policy_adjusted_count": total_adjusted,
            "fallback_rate": round(total_fallbacks / total_decisions, 4) if total_decisions else 0.0,
            "policy_adjusted_rate": round(total_adjusted / total_decisions, 4) if total_decisions else 0.0,
            "avg_confidence": round(sum(g.avg_confidence for g in self.games) / n, 3) if n else 0.0,
            "confidence_calibration_error": round(calibration["confidence_calibration_error"], 3),
            "confidence_calibration_count": calibration["confidence_calibration_count"],
            "confidence_buckets": calibration["confidence_buckets"],
            "mistake_count": sum(g.mistake_count for g in self.games),
            "counterfactual_count": sum(g.counterfactual_count for g in self.games),
            "turning_point_count": sum(g.turning_point_count for g in self.games),
            # Leaderboard fields — aggregated by aggregate_summaries in leaderboard.py
            "bad_case_count": sum(g.mistake_count for g in self.games),
            "turning_point_quality": 0.0,  # TODO: wire up when turning point quality scoring is implemented
            "tot_usage_rate": 0.0,  # TODO: wire up when ToT usage tracking is implemented
            "got_trigger_count": 0,  # TODO: wire up when GoT trigger tracking is implemented
            "got_failure_count": 0,  # TODO: wire up when GoT failure tracking is implemented
            "information_score": round(sum(g.information_score for g in reviewed) / len(reviewed), 3) if reviewed else 0.0,
            "cooperation_score": round(sum(g.cooperation_score for g in reviewed) / len(reviewed), 3) if reviewed else 0.0,
            "by_role": {},  # TODO: wire up per-role stats aggregation
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
            f"| Policy 修正率 | {s['policy_adjusted_rate']:.1%} |",
            f"| 平均置信度 | {s['avg_confidence']:.1%} |",
            f"| 置信度校准误差 | {s['confidence_calibration_error']:.1%} ({s['confidence_calibration_count']} samples) |",
            "",
            "## Per-Game Results",
            "",
        ]
        lines.append("| Game | Seed | Winner | Days | Decisions | Fallback | Adjusted | Conf | Score |")
        lines.append("|------|------|--------|------|-----------|----------|----------|------|-------|")
        for g in self.games:
            desc = g.game_id
            score_str = f"{g.review_score:.1f}" if g.review_score is not None else "-"
            lines.append(
                f"| {desc} | {g.seed} | {g.winner} | {g.days} | "
                f"{g.decision_count} | {g.fallback_count} | {g.policy_adjusted_count} | "
                f"{g.avg_confidence:.2f} | {score_str} |"
            )
        lines.append("")
        return "\n".join(lines)

    def write_summary(self, output_dir: Path) -> None:
        """Write summary.json and summary.md to the output directory."""
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(self.summary, f, ensure_ascii=False, indent=2)
        with open(output_dir / "summary.md", "w", encoding="utf-8") as f:
            f.write(self.summary_markdown())


async def run_selfplay(
    config: SelfPlayConfig,
    *,
    model: ModelAdapter | None = None,
    client_factory=None,
    on_game_complete: "Callable[[int, SelfPlayGameResult], None] | None" = None,
) -> SelfPlayResult:
    """Run a multi-game selfplay session.

    Args:
        config: Selfplay configuration.
        model: Shared model adapter. If None, uses load_llm_client() per game.
        client_factory: Optional callable that returns a ModelAdapter per game.
        on_game_complete: Optional callback ``(game_index, game_result)``
            invoked after each game finishes.  *game_index* is zero-based.
    """
    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    started_at = _now()
    run_dir = config.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Write config
    _write_json(run_dir / "config.json", {
        "games": config.games,
        "seed_start": config.seed_start,
        "agent_version": config.agent_version,
        "model_name": config.model_name,
        "max_days": config.max_days,
        "temperature": config.temperature,
        "enable_review": config.enable_review,
        "enable_experience": config.enable_experience,
        "enable_dream": config.enable_dream,
        "enable_batch_dream": config.enable_batch_dream,
        "enable_skill_proposals": config.enable_skill_proposals,
        "auto_apply_skill_proposals": config.auto_apply_skill_proposals,
        "skill_dir": str(config.skill_dir) if config.skill_dir else None,
    })

    results: list[SelfPlayGameResult] = []
    _frozen_skill_dir = config.skill_dir
    batch_client: ModelAdapter | None = None

    for i in range(config.games):
        assert config.skill_dir == _frozen_skill_dir, (
            f"skill_dir changed mid-run: {_frozen_skill_dir} -> {config.skill_dir}"
        )
        seed = config.seed_start + i
        game_id = f"game_{i + 1:03d}"
        game_dir = run_dir / "games" / game_id
        game_dir.mkdir(parents=True, exist_ok=True)

        # Create roles using the game config
        roles = assign_roles(config.game_config, seed=seed)
        player_roles = {pid: r.value for pid, r in roles.items()}

        # Create per-agent trace recorders
        trace_recorders: dict[int, AgentTraceRecorder] = {
            pid: AgentTraceRecorder() for pid in roles
        }

        # Create agents with trace recorders
        decision_recorder = AgentDecisionRecorder()
        configure_skill_root(config.skill_dir)
        client = client_factory() if client_factory else model
        if client is None:
            client = load_llm_client(
                model_name=config.model_name,
                temperature=config.temperature,
            )
        batch_client = client
        agents = _create_agents(
            roles, client, decision_recorder, trace_recorders,
            skill_dir=config.skill_dir,
        )

        # Run game
        engine = GameEngine(roles, agents, config.game_config)
        try:
            winner = await engine.run_until_finished(max_days=config.max_days)
        except Exception as exc:
            winner = type("Winner", (), {"value": f"error:{exc}"})()

        winner_str = winner.value if hasattr(winner, "value") else str(winner)

        # Determine if game failed
        game_error: str | None = None
        if winner_str.startswith("error:"):
            game_error = winner_str[6:]
            winner_str = "error"

        # Write game events
        _write_jsonl(game_dir / "game_events.jsonl", engine.logger.entries)
        _write_jsonl(game_dir / "agent_decisions.jsonl", decision_recorder.records)

        # Collect trace snapshots — merge all players into one archive
        all_decisions: list[DecisionArchive] = []
        for recorder in trace_recorders.values():
            all_decisions.extend(recorder.snapshot())

        # Write single merged archive and trace file
        merged_archive = GameArchive(
            game_id=game_id,
            seed=seed,
            config={
                "agent_version": config.agent_version,
                "skill_dir": str(config.skill_dir) if config.skill_dir else None,
            },
            player_roles=player_roles,
            winner=winner_str,
            started_at=_now(),
            finished_at=_now(),
            public_events=[e.to_dict() for e in engine.state.events],
            decisions=all_decisions,
            final_state={"player_roles": player_roles, "winner": winner_str},
        )
        merged_archive.write_json(game_dir / "archive.json")
        _write_jsonl(game_dir / "agent_traces.jsonl", all_decisions)

        # Collect stats
        fallback_count = 0
        policy_adjusted_count = 0
        total_decisions = 0
        total_confidence = 0.0
        for rec in decision_recorder.records:
            total_decisions += 1
            if getattr(rec, "source", "") == "fallback":
                fallback_count += 1
            elif getattr(rec, "source", "") == "policy_adjusted":
                policy_adjusted_count += 1
            total_confidence += getattr(rec, "confidence", 0.0) or 0.0

        avg_confidence = total_confidence / total_decisions if total_decisions else 0.0
        calibration = calibrate_decisions(decision_recorder.records, roles)

        # Review (enhanced) — skip for errored games
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
        if config.enable_review and not game_error:
            agent_decisions = _collect_decisions(decision_recorder)
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
            vote_accuracy = avg_vote_score / 10.0
            skill_accuracy = avg_skill_score / 10.0
            mistake_count = len(review_report.mistakes)
            counterfactual_count = len(review_report.counterfactuals)
            turning_point_count = len(review_report.key_turning_points)
            information_score = sum(s.information_score for s in player_scores) / denominator
            cooperation_score = sum(s.cooperation_score for s in player_scores) / denominator
            role_weighted_score = sum(s.role_weighted_score for s in player_scores) / denominator
            _write_json(game_dir / "review.json", review_report.to_dict())
            _write_text(game_dir / "review.md", review_report.to_markdown())

        # Experience cards — skip for errored games
        if config.enable_experience and review_report is not None:
            agent_decisions = _collect_decisions(decision_recorder)
            cards = extract_experiences(
                game_id=game_id,
                roles=roles,
                agent_decisions=agent_decisions,
                review=review_report,
                winner_team=winner_str,
            )
            write_game_experiences(
                cards=cards,
                game_dir=game_dir,
                output_dir=run_dir / "experiences",
            )
            if config.enable_dream:
                by_role: dict[Role, list] = {}
                for card in cards:
                    try:
                        role = Role(card.role)
                    except ValueError:
                        continue
                    by_role.setdefault(role, []).append(card)
                for role, role_cards in sorted(by_role.items(), key=lambda item: item[0].value):
                    rule_memory = consolidate_role_memory(role)
                    write_role_memory(
                        rule_memory,
                        output_dir=game_dir / "long_memory",
                    )
                    write_memory_candidate(
                        rule_memory,
                        output_dir=run_dir / "memory_candidate",
                    )
                    report = await dream_for_role(
                        role=role,
                        model=client,
                        cards=role_cards,
                        rule_memory=rule_memory,
                        skill_root=config.skill_dir,
                    )
                    write_dream_report(
                        report,
                        output_dir=game_dir / "dreams" / role.value,
                    )
                    if config.enable_skill_proposals:
                        proposals = proposals_from_dream(report)
                        write_skill_proposals(
                            proposals,
                            output_dir=game_dir / "skill_proposals" / role.value,
                        )
                        if config.auto_apply_skill_proposals:
                            apply_skill_proposals(
                                proposals,
                                target_skill_root=config.skill_dir,
                                patch_dir=game_dir / "skill_patches" / role.value,
                            )

        # Write meta
        _write_json(game_dir / "meta.json", {
            "game_id": game_id,
            "seed": seed,
            "agent_version": config.agent_version,
            "winner": winner_str,
            "days": engine.state.day,
            "players": player_roles,
        })

        result = SelfPlayGameResult(
            game_id=game_id,
            seed=seed,
            winner=winner_str,
            days=engine.state.day,
            player_roles=player_roles,
            decision_count=total_decisions,
            fallback_count=fallback_count,
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
            error=game_error,
        )
        results.append(result)
        if on_game_complete is not None:
            on_game_complete(i, result)

    if (
        config.enable_batch_dream
        and config.enable_experience
        and results
    ):
        if batch_client is None:
            batch_client = load_llm_client(
                model_name=config.model_name,
                temperature=config.temperature,
            )
        await _run_batch_dream(
            run_dir=run_dir,
            model=batch_client,
            skill_dir=config.skill_dir,
            enable_skill_proposals=config.enable_skill_proposals,
            auto_apply_skill_proposals=config.auto_apply_skill_proposals,
        )

    selfplay_result = SelfPlayResult(
        config=config,
        games=results,
        run_id=run_id,
        started_at=started_at,
        finished_at=_now(),
    )

    # Write summary
    selfplay_result.write_summary(run_dir)
    return selfplay_result


async def _run_batch_dream(
    *,
    run_dir: Path,
    model: ModelAdapter,
    skill_dir: Path | None,
    enable_skill_proposals: bool,
    auto_apply_skill_proposals: bool,
) -> None:
    cards_by_role = _collect_run_experience_cards(run_dir)
    for role, cards in sorted(cards_by_role.items(), key=lambda item: item[0].value):
        rule_memory = consolidate_role_memory(
            role,
            experience_dir=run_dir / "experiences",
            min_evidence=2,
        )
        write_role_memory(rule_memory, output_dir=run_dir / "long_memory")
        write_memory_candidate(rule_memory, output_dir=run_dir / "memory_candidate")
        report = await dream_for_role(
            role=role,
            model=model,
            cards=cards,
            rule_memory=rule_memory,
            skill_root=skill_dir,
        )
        write_dream_report(
            report,
            output_dir=run_dir / "batch_dreams" / role.value,
        )
        if not enable_skill_proposals:
            continue
        proposals = proposals_from_dream(
            report,
            min_confidence=0.75,
            min_evidence_cards=2,
        )
        write_skill_proposals(
            proposals,
            output_dir=run_dir / "batch_skill_proposals" / role.value,
        )
        if auto_apply_skill_proposals and skill_dir is not None:
            apply_skill_proposals(
                proposals,
                target_skill_root=skill_dir,
                patch_dir=run_dir / "batch_skill_patches" / role.value,
                min_confidence=0.75,
                min_evidence_cards=2,
            )


def _collect_run_experience_cards(run_dir: Path) -> dict[Role, list[dict]]:
    cards_by_role: dict[Role, list[dict]] = {}
    for path in sorted((run_dir / "games").glob("*/experiences/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            role = Role(str(data.get("role", "")))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        cards_by_role.setdefault(role, []).append(data)
    return cards_by_role


def _create_agents(
    roles: dict[int, Role],
    client: ModelAdapter | None,
    decision_recorder: AgentDecisionRecorder,
    trace_recorders: dict[int, AgentTraceRecorder],
    game_id: str | None = None,
    skill_dir: Path | None = None,
) -> dict[int, LLMPlayerAgent]:
    """Create a full set of LLMPlayerAgent with trace recorders."""
    agents: dict[int, LLMPlayerAgent] = {}
    for player_id, role in sorted(roles.items()):
        agent = LLMPlayerAgent(
            player_id=player_id,
            role=role,
            client=client,
            decision_recorder=decision_recorder,
            game_id=game_id,
            skill_dir=skill_dir,
        )
        # Wire trace recorder into the runtime
        agent.runtime.trace_recorder = trace_recorders.get(player_id)
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_jsonl(path: Path, entries: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            data = entry.to_dict() if hasattr(entry, "to_dict") else entry
            f.write(json.dumps(data, ensure_ascii=False) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _is_werewolf_winner(winner: str) -> bool:
    """Check if winner string indicates werewolf victory."""
    w = winner.lower()
    return w in ("werewolves", "werewolf") or "werewolf" in w
