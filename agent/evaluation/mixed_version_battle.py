"""Team-level mixed-version battle.

Runs mirrored games where one agent version controls the werewolf team and
another version controls the villager/god team.  This is stricter than ordinary
version battle because both versions are present in the same game.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from agent.evaluation.confidence_calibration import calibrate_decisions_by_group, merge_calibration_reports
from agent.evaluation.leaderboard import LeaderboardEntry, annotate_vs_baseline, build_leaderboard, write_leaderboard
from agent.evaluation.review_enhanced import generate_enhanced_review
from agent.evaluation.statistics import mean_ci95, wilson_ci95
from agent.evaluation.version_battle import VersionSpec
from agent.observability.archive import AgentTraceRecorder, DecisionArchive, GameArchive
from agent.observability.decision_log import AgentDecisionRecorder
from agent.runtime.agent import LLMPlayerAgent
from agent.runtime.factory import load_llm_client
from agent.runtime.model import ModelAdapter
from engine.config import GameConfig, STANDARD_12
from engine.engine import GameEngine
from engine.models import Role, Team
from engine.roles import assign_roles


@dataclass(slots=True)
class TeamVersionMatchup:
    """One pair of versions to compare inside the same games."""

    version_a: VersionSpec
    version_b: VersionSpec
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_a": self.version_a.to_dict(),
            "version_b": self.version_b.to_dict(),
            "label": self.label,
        }


@dataclass(slots=True)
class MixedVersionBattleConfig:
    """Configuration for team-level mixed-version battle."""

    matchup: TeamVersionMatchup
    games_per_side: int
    seed_start: int = 1
    output_dir: Path = Path("runs/mixed_version_battle")
    max_days: int = 20
    enable_review: bool = True
    game_config: GameConfig = STANDARD_12

    def to_dict(self) -> dict[str, Any]:
        return {
            "matchup": self.matchup.to_dict(),
            "games_per_side": self.games_per_side,
            "seed_start": self.seed_start,
            "output_dir": str(self.output_dir),
            "max_days": self.max_days,
            "enable_review": self.enable_review,
            "game_config": self.game_config.name,
        }


@dataclass(slots=True)
class MixedGameConfig:
    game_id: str
    seed: int
    wolves_version: VersionSpec
    villagers_version: VersionSpec
    output_dir: Path
    max_days: int
    enable_review: bool
    game_config: GameConfig = STANDARD_12


@dataclass(slots=True)
class MixedGameResult:
    game_id: str
    seed: int
    wolves_version: str
    villagers_version: str
    winner: str
    days: int
    player_roles: dict[int, str]
    player_versions: dict[int, str]
    decision_count_by_version: dict[str, int] = field(default_factory=dict)
    fallback_count_by_version: dict[str, int] = field(default_factory=dict)
    policy_adjusted_count_by_version: dict[str, int] = field(default_factory=dict)
    confidence_by_version: dict[str, float] = field(default_factory=dict)
    confidence_calibration_error_by_version: dict[str, float] = field(default_factory=dict)
    confidence_calibration_count_by_version: dict[str, int] = field(default_factory=dict)
    confidence_buckets_by_version: dict[str, dict] = field(default_factory=dict)
    review_score_by_version: dict[str, float] = field(default_factory=dict)
    role_weighted_score_by_version: dict[str, float] = field(default_factory=dict)
    speech_score_by_version: dict[str, float] = field(default_factory=dict)
    vote_score_by_version: dict[str, float] = field(default_factory=dict)
    skill_score_by_version: dict[str, float] = field(default_factory=dict)
    information_score_by_version: dict[str, float] = field(default_factory=dict)
    cooperation_score_by_version: dict[str, float] = field(default_factory=dict)
    mistake_count_by_version: dict[str, int] = field(default_factory=dict)
    output_dir: Path = Path(".")
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "game_id": self.game_id,
            "seed": self.seed,
            "wolves_version": self.wolves_version,
            "villagers_version": self.villagers_version,
            "winner": self.winner,
            "days": self.days,
            "player_roles": {str(k): v for k, v in self.player_roles.items()},
            "player_versions": {str(k): v for k, v in self.player_versions.items()},
            "decision_count_by_version": self.decision_count_by_version,
            "fallback_count_by_version": self.fallback_count_by_version,
            "policy_adjusted_count_by_version": self.policy_adjusted_count_by_version,
            "confidence_by_version": self.confidence_by_version,
            "confidence_calibration_error_by_version": self.confidence_calibration_error_by_version,
            "confidence_calibration_count_by_version": self.confidence_calibration_count_by_version,
            "confidence_buckets_by_version": self.confidence_buckets_by_version,
            "review_score_by_version": self.review_score_by_version,
            "role_weighted_score_by_version": self.role_weighted_score_by_version,
            "speech_score_by_version": self.speech_score_by_version,
            "vote_score_by_version": self.vote_score_by_version,
            "skill_score_by_version": self.skill_score_by_version,
            "information_score_by_version": self.information_score_by_version,
            "cooperation_score_by_version": self.cooperation_score_by_version,
            "mistake_count_by_version": self.mistake_count_by_version,
            "output_dir": str(self.output_dir),
        }
        if self.error:
            data["error"] = self.error
        return data


@dataclass(slots=True)
class MixedVersionBattleResult:
    config: MixedVersionBattleConfig
    games: list[MixedGameResult]
    leaderboard: list[LeaderboardEntry]
    output_dir: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "games": [game.to_dict() for game in self.games],
            "leaderboard": [entry.to_dict() for entry in self.leaderboard],
            "output_dir": str(self.output_dir),
        }


RunMixedGameFunc = Callable[..., Awaitable[MixedGameResult]]


async def run_team_mixed_version_battle(
    config: MixedVersionBattleConfig,
    *,
    model: ModelAdapter | None = None,
    client_factory=None,
    game_runner: RunMixedGameFunc | None = None,
) -> MixedVersionBattleResult:
    """Run mirrored team-level mixed-version games and write artifacts."""
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(config.output_dir / "mixed_version_battle_config.json", config.to_dict())

    runner = game_runner or _run_mixed_game
    games: list[MixedGameResult] = []

    for i in range(config.games_per_side):
        seed = config.seed_start + i
        first = MixedGameConfig(
            game_id=f"mixed_{i + 1:03d}_a",
            seed=seed,
            wolves_version=config.matchup.version_a,
            villagers_version=config.matchup.version_b,
            output_dir=config.output_dir / "games" / f"mixed_{i + 1:03d}_a",
            max_days=config.max_days,
            enable_review=config.enable_review,
            game_config=config.game_config,
        )
        second = MixedGameConfig(
            game_id=f"mixed_{i + 1:03d}_b",
            seed=seed,
            wolves_version=config.matchup.version_b,
            villagers_version=config.matchup.version_a,
            output_dir=config.output_dir / "games" / f"mixed_{i + 1:03d}_b",
            max_days=config.max_days,
            enable_review=config.enable_review,
            game_config=config.game_config,
        )
        games.append(await runner(first, model=model, client_factory=client_factory))
        games.append(await runner(second, model=model, client_factory=client_factory))

    entries = _build_mixed_leaderboard(games)
    annotate_vs_baseline(entries, config.matchup.version_a.name)
    leaderboard = build_leaderboard(entries)
    write_leaderboard(leaderboard, config.output_dir)

    result = MixedVersionBattleResult(
        config=config,
        games=games,
        leaderboard=leaderboard,
        output_dir=config.output_dir,
    )
    _write_json(config.output_dir / "mixed_version_battle_result.json", result.to_dict())
    return result


async def _run_mixed_game(
    config: MixedGameConfig,
    *,
    model: ModelAdapter | None = None,
    client_factory=None,
) -> MixedGameResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    roles = assign_roles(config.game_config, seed=config.seed)
    player_roles = {pid: role.value for pid, role in roles.items()}
    player_versions = {
        pid: _version_for_role(role, config.wolves_version, config.villagers_version).name
        for pid, role in roles.items()
    }

    decision_recorder = AgentDecisionRecorder()
    trace_recorders = {pid: AgentTraceRecorder() for pid in roles}
    clients = {
        config.wolves_version.name: _load_version_client(config.wolves_version, model, client_factory),
        config.villagers_version.name: _load_version_client(config.villagers_version, model, client_factory),
    }
    agents: dict[int, LLMPlayerAgent] = {}
    for player_id, role in sorted(roles.items()):
        spec = _version_for_role(role, config.wolves_version, config.villagers_version)
        agents[player_id] = LLMPlayerAgent(
            player_id=player_id,
            role=role,
            client=clients[spec.name],
            decision_recorder=decision_recorder,
            trace_recorder=trace_recorders[player_id],
            game_id=config.game_id,
            skill_dir=spec.skill_dir,
        )

    engine = GameEngine(roles, agents, config.game_config)
    try:
        winner = await engine.run_until_finished(max_days=config.max_days)
        winner_str = winner.value if hasattr(winner, "value") else str(winner)
        game_error = None
    except Exception as exc:
        winner_str = "error"
        game_error = str(exc)

    _write_jsonl(config.output_dir / "game_events.jsonl", engine.logger.entries)
    _write_jsonl(config.output_dir / "agent_decisions.jsonl", [
        _decision_with_version(record, player_versions)
        for record in decision_recorder.records
    ])

    all_decisions: list[DecisionArchive] = []
    for recorder in trace_recorders.values():
        all_decisions.extend(recorder.snapshot())
    archive = GameArchive(
        game_id=config.game_id,
        seed=config.seed,
        config={
            "wolves_version": config.wolves_version.name,
            "villagers_version": config.villagers_version.name,
        },
        player_roles=player_roles,
        winner=winner_str,
        started_at=_now(),
        finished_at=_now(),
        public_events=[event.to_dict() for event in engine.state.events],
        decisions=all_decisions,
        final_state={
            "player_roles": player_roles,
            "player_versions": player_versions,
            "winner": winner_str,
        },
    )
    archive.write_json(config.output_dir / "archive.json")

    stats = _decision_stats_by_version(decision_recorder, player_versions, roles)
    review_stats: dict[str, dict[str, float | int]] = {}
    if config.enable_review and not game_error:
        review_report = generate_enhanced_review(
            game_log={"entries": [event.to_dict() for event in engine.logger.entries]},
            agent_decisions=_collect_decisions(decision_recorder),
            roles=roles,
            winner_team=winner_str,
            game_id=config.game_id,
        )
        _write_json(config.output_dir / "review.json", review_report.to_dict())
        _write_text(config.output_dir / "review.md", review_report.to_markdown())
        review_stats = _review_stats_by_version(review_report, player_versions)

    result = MixedGameResult(
        game_id=config.game_id,
        seed=config.seed,
        wolves_version=config.wolves_version.name,
        villagers_version=config.villagers_version.name,
        winner=winner_str,
        days=engine.state.day,
        player_roles=player_roles,
        player_versions=player_versions,
        decision_count_by_version=stats["decisions"],
        fallback_count_by_version=stats["fallbacks"],
        policy_adjusted_count_by_version=stats["adjusted"],
        confidence_by_version=stats["confidence"],
        confidence_calibration_error_by_version=stats["calibration_error"],
        confidence_calibration_count_by_version=stats["calibration_count"],
        confidence_buckets_by_version=stats["calibration_buckets"],
        review_score_by_version=_review_metric(review_stats, "score"),
        role_weighted_score_by_version=_review_metric(review_stats, "role_weighted"),
        speech_score_by_version=_review_metric(review_stats, "speech"),
        vote_score_by_version=_review_metric(review_stats, "vote"),
        skill_score_by_version=_review_metric(review_stats, "skill"),
        information_score_by_version=_review_metric(review_stats, "information"),
        cooperation_score_by_version=_review_metric(review_stats, "cooperation"),
        mistake_count_by_version=_review_int_metric(review_stats, "mistakes"),
        output_dir=config.output_dir,
        error=game_error,
    )
    _write_json(config.output_dir / "meta.json", result.to_dict())
    return result


def _build_mixed_leaderboard(games: list[MixedGameResult]) -> list[LeaderboardEntry]:
    stats: dict[str, dict[str, float]] = {}
    for game in games:
        for version, side in (
            (game.wolves_version, "wolves"),
            (game.villagers_version, "villagers"),
        ):
            row = stats.setdefault(version, {
                "games": 0,
                "wolves_games": 0,
                "villager_games": 0,
                "wolves_wins": 0,
                "villager_wins": 0,
                "days": 0,
                "score": 0,
                "role_weighted": 0,
                "speech": 0,
                "vote": 0,
                "skill": 0,
                "confidence": 0,
                "calibration_reports": [],
                "fallbacks": 0,
                "decisions": 0,
                "adjusted": 0,
                "information": 0,
                "cooperation": 0,
                "mistakes": 0,
                "score_samples": [],
                "role_weighted_samples": [],
            })
            row["games"] += 1
            row["days"] += game.days
            row["score"] += game.review_score_by_version.get(version, 0.0)
            row["role_weighted"] += game.role_weighted_score_by_version.get(version, 0.0)
            row["score_samples"].append(game.review_score_by_version.get(version, 0.0))
            row["role_weighted_samples"].append(game.role_weighted_score_by_version.get(version, 0.0))
            row["speech"] += game.speech_score_by_version.get(version, 0.0)
            row["vote"] += game.vote_score_by_version.get(version, 0.0)
            row["skill"] += game.skill_score_by_version.get(version, 0.0)
            row["confidence"] += game.confidence_by_version.get(version, 0.0)
            row["calibration_reports"].append({
                "confidence_calibration_error": game.confidence_calibration_error_by_version.get(version, 0.0),
                "confidence_calibration_count": game.confidence_calibration_count_by_version.get(version, 0),
                "confidence_buckets": game.confidence_buckets_by_version.get(version, {}),
            })
            row["fallbacks"] += game.fallback_count_by_version.get(version, 0)
            row["decisions"] += game.decision_count_by_version.get(version, 0)
            row["adjusted"] += game.policy_adjusted_count_by_version.get(version, 0)
            row["information"] += game.information_score_by_version.get(version, 0.0)
            row["cooperation"] += game.cooperation_score_by_version.get(version, 0.0)
            row["mistakes"] += game.mistake_count_by_version.get(version, 0)
            if side == "wolves":
                row["wolves_games"] += 1
                if _is_werewolf_winner(game.winner):
                    row["wolves_wins"] += 1
            else:
                row["villager_games"] += 1
                if _is_villager_winner(game.winner):
                    row["villager_wins"] += 1

    entries: list[LeaderboardEntry] = []
    for version, row in stats.items():
        games_count = int(row["games"])
        decisions = row["decisions"]
        calibration = merge_calibration_reports(row["calibration_reports"])
        entries.append(LeaderboardEntry(
            version=version,
            games=games_count,
            werewolf_win_rate=row["wolves_wins"] / row["wolves_games"] if row["wolves_games"] else 0.0,
            villager_win_rate=row["villager_wins"] / row["villager_games"] if row["villager_games"] else 0.0,
            werewolf_win_rate_ci95=wilson_ci95(int(row["wolves_wins"]), int(row["wolves_games"])),
            villager_win_rate_ci95=wilson_ci95(int(row["villager_wins"]), int(row["villager_games"])),
            avg_days=row["days"] / games_count if games_count else 0.0,
            avg_score=row["score"] / games_count if games_count else 0.0,
            avg_score_ci95=mean_ci95(row["score_samples"]),
            role_weighted_score=row["role_weighted"] / games_count if games_count else 0.0,
            role_weighted_score_ci95=mean_ci95(row["role_weighted_samples"]),
            avg_speech_score=row["speech"] / games_count if games_count else 0.0,
            avg_vote_score=row["vote"] / games_count if games_count else 0.0,
            avg_skill_score=row["skill"] / games_count if games_count else 0.0,
            avg_confidence=row["confidence"] / games_count if games_count else 0.0,
            confidence_calibration_error=calibration["confidence_calibration_error"],
            confidence_calibration_count=calibration["confidence_calibration_count"],
            confidence_buckets=calibration["confidence_buckets"],
            fallback_rate=row["fallbacks"] / decisions if decisions else 0.0,
            policy_adjusted_rate=row["adjusted"] / decisions if decisions else 0.0,
            bad_case_count=row["mistakes"] / games_count if games_count else 0.0,
            information_score=row["information"] / games_count if games_count else 0.0,
            cooperation_score=row["cooperation"] / games_count if games_count else 0.0,
            notes="team-level mixed battle",
        ))
    return entries


def _version_for_role(role: Role, wolves_version: VersionSpec, villagers_version: VersionSpec) -> VersionSpec:
    return wolves_version if role.team is Team.WEREWOLVES else villagers_version


def _load_version_client(spec: VersionSpec, model: ModelAdapter | None, client_factory) -> ModelAdapter:
    if model is not None:
        return model
    if client_factory is not None:
        try:
            return client_factory(spec)
        except TypeError:
            return client_factory()
    return load_llm_client(
        model_name=spec.model_name,
        temperature=spec.temperature if spec.temperature is not None else 0.2,
    )


def _decision_with_version(record: Any, player_versions: dict[int, str]) -> dict[str, Any]:
    data = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    player_id = data.get("player_id")
    if player_id in player_versions:
        data["version"] = player_versions[player_id]
    return data


def _decision_stats_by_version(
    recorder: AgentDecisionRecorder,
    player_versions: dict[int, str],
    roles: dict[int, Role],
) -> dict[str, dict[str, int | float]]:
    decisions: dict[str, int] = {}
    fallbacks: dict[str, int] = {}
    adjusted: dict[str, int] = {}
    confidence_total: dict[str, float] = {}
    for record in recorder.records:
        if record.player_id is None:
            continue
        version = player_versions.get(record.player_id)
        if not version:
            continue
        decisions[version] = decisions.get(version, 0) + 1
        confidence_total[version] = confidence_total.get(version, 0.0) + (record.confidence or 0.0)
        if record.source == "fallback":
            fallbacks[version] = fallbacks.get(version, 0) + 1
        if record.source == "policy_adjusted":
            adjusted[version] = adjusted.get(version, 0) + 1
    confidence = {
        version: confidence_total[version] / count
        for version, count in decisions.items()
        if count
    }
    calibration = calibrate_decisions_by_group(
        recorder.records,
        roles,
        lambda player_id: player_versions.get(player_id),
    )
    return {
        "decisions": decisions,
        "fallbacks": fallbacks,
        "adjusted": adjusted,
        "confidence": confidence,
        "calibration_error": {
            version: report["confidence_calibration_error"]
            for version, report in calibration.items()
        },
        "calibration_count": {
            version: report["confidence_calibration_count"]
            for version, report in calibration.items()
        },
        "calibration_buckets": {
            version: report["confidence_buckets"]
            for version, report in calibration.items()
        },
    }


def _review_stats_by_version(review_report: Any, player_versions: dict[int, str]) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[Any]] = {}
    for player_id, score in review_report.player_scores.items():
        version = player_versions.get(player_id)
        if version:
            grouped.setdefault(version, []).append(score)

    mistakes_by_version: dict[str, int] = {}
    for mistake in review_report.mistakes:
        version = player_versions.get(getattr(mistake, "player_id", None))
        if version:
            mistakes_by_version[version] = mistakes_by_version.get(version, 0) + 1

    result: dict[str, dict[str, float | int]] = {}
    for version, scores in grouped.items():
        denominator = max(len(scores), 1)
        result[version] = {
            "score": sum(score.total_score for score in scores) / denominator,
            "speech": sum(score.speech_score for score in scores) / denominator,
            "vote": sum(score.vote_score for score in scores) / denominator,
            "skill": sum(score.skill_score for score in scores) / denominator,
            "information": sum(score.information_score for score in scores) / denominator,
            "cooperation": sum(score.cooperation_score for score in scores) / denominator,
            "role_weighted": sum(score.role_weighted_score for score in scores) / denominator,
            "mistakes": mistakes_by_version.get(version, 0),
        }
    return result


def _review_metric(stats: dict[str, dict[str, float | int]], key: str) -> dict[str, float]:
    return {version: float(values.get(key, 0.0)) for version, values in stats.items()}


def _review_int_metric(stats: dict[str, dict[str, float | int]], key: str) -> dict[str, int]:
    return {version: int(values.get(key, 0)) for version, values in stats.items()}


def _collect_decisions(recorder: AgentDecisionRecorder) -> dict[int, list[dict]]:
    decisions: dict[int, list[dict]] = {}
    for record in recorder.records:
        if record.player_id is not None:
            decisions.setdefault(record.player_id, []).append(record.to_dict())
    return decisions


def _is_werewolf_winner(winner: str) -> bool:
    return winner.lower() in {"werewolves", "werewolf"} or "werewolf" in winner.lower()


def _is_villager_winner(winner: str) -> bool:
    return winner.lower() in {"villagers", "villager"} or "villager" in winner.lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, entries: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for entry in entries:
        data = entry.to_dict() if hasattr(entry, "to_dict") else entry
        lines.append(json.dumps(data, ensure_ascii=False))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
