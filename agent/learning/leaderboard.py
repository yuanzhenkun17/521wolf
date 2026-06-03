"""Leaderboard — multi-version agent comparison across selfplay runs.

Aggregates results from multiple selfplay runs and produces
comparable metrics in JSON and markdown table formats.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from agent.learning.stats import merge_calibration_reports, mean_ci95, wilson_ci95


@dataclass(slots=True)
class LeaderboardEntry:
    """A single row in the leaderboard — aggregated metrics for one version.

    All metrics should be normalized (e.g. rates 0.0–1.0, scores 0.0–10.0).
    """

    version: str
    games: int = 0
    werewolf_win_rate: float = 0.0
    villager_win_rate: float = 0.0
    avg_days: float = 0.0
    avg_score: float = 0.0
    avg_score_ci95: tuple[float, float] = (0.0, 0.0)
    role_weighted_score: float = 0.0
    role_weighted_score_ci95: tuple[float, float] = (0.0, 0.0)
    score_delta_vs_base: float = 0.0
    significant_vs_base: bool = False
    avg_speech_score: float = 0.0
    avg_vote_score: float = 0.0
    avg_skill_score: float = 0.0
    avg_confidence: float = 0.0
    confidence_calibration_error: float = 0.0
    confidence_calibration_count: int = 0
    confidence_buckets: dict = field(default_factory=dict)
    fallback_rate: float = 0.0
    vote_accuracy: float = 0.0
    skill_accuracy: float = 0.0
    policy_adjusted_rate: float = 0.0
    bad_case_count: float = 0.0
    werewolf_win_rate_ci95: tuple[float, float] = (0.0, 0.0)
    villager_win_rate_ci95: tuple[float, float] = (0.0, 0.0)
    turning_point_quality: float = 0.0
    information_score: float = 0.0
    cooperation_score: float = 0.0
    by_role: dict = field(default_factory=dict)
    notes: str = ""
    run_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "games": self.games,
            "werewolf_win_rate": round(self.werewolf_win_rate, 3),
            "villager_win_rate": round(self.villager_win_rate, 3),
            "avg_days": round(self.avg_days, 2),
            "avg_score": round(self.avg_score, 2),
            "avg_score_ci95": [round(self.avg_score_ci95[0], 2), round(self.avg_score_ci95[1], 2)],
            "role_weighted_score": round(self.role_weighted_score, 2),
            "role_weighted_score_ci95": [
                round(self.role_weighted_score_ci95[0], 2),
                round(self.role_weighted_score_ci95[1], 2),
            ],
            "score_delta_vs_base": round(self.score_delta_vs_base, 3),
            "significant_vs_base": self.significant_vs_base,
            "avg_speech_score": round(self.avg_speech_score, 2),
            "avg_vote_score": round(self.avg_vote_score, 2),
            "avg_skill_score": round(self.avg_skill_score, 2),
            "avg_confidence": round(self.avg_confidence, 3),
            "confidence_calibration_error": round(self.confidence_calibration_error, 3),
            "confidence_calibration_count": self.confidence_calibration_count,
            "confidence_buckets": self.confidence_buckets,
            "fallback_rate": round(self.fallback_rate, 4),
            "vote_accuracy": round(self.vote_accuracy, 3),
            "skill_accuracy": round(self.skill_accuracy, 3),
            "policy_adjusted_rate": round(self.policy_adjusted_rate, 4),
            "bad_case_count": round(self.bad_case_count, 1),
            "werewolf_win_rate_ci95": [
                round(self.werewolf_win_rate_ci95[0], 3),
                round(self.werewolf_win_rate_ci95[1], 3),
            ],
            "villager_win_rate_ci95": [
                round(self.villager_win_rate_ci95[0], 3),
                round(self.villager_win_rate_ci95[1], 3),
            ],
            "turning_point_quality": round(self.turning_point_quality, 3),
            "information_score": round(self.information_score, 3),
            "cooperation_score": round(self.cooperation_score, 3),
            "by_role": self.by_role,
            "notes": self.notes,
            "run_ids": self.run_ids,
        }


def aggregate_summaries(
    summaries: list[dict],
    version: str | None = None,
    label: str | None = None,
) -> LeaderboardEntry:
    """Build a single LeaderboardEntry from multiple run summaries."""
    n = len(summaries)
    entry_version = label or version or "unknown"
    if n == 0:
        return LeaderboardEntry(version=entry_version)

    total_games = sum(s.get("games", 0) for s in summaries)
    total_normal = sum(
        s.get("games", 0) - s.get("error_count", 0)
        for s in summaries
    )
    wolves = sum(s.get("werewolf_wins", 0) for s in summaries)
    villagers = sum(s.get("villager_wins", 0) for s in summaries)
    avg_days = sum(s.get("avg_days", 0) * s.get("games", 0) for s in summaries)
    avg_score = sum(s.get("avg_decision_score", 0) * s.get("games", 0) for s in summaries)
    role_weighted = sum(s.get("role_weighted_score", s.get("avg_decision_score", 0)) * s.get("games", 0) for s in summaries)
    speech = sum(s.get("avg_speech_score", 0) * s.get("games", 0) for s in summaries)
    vote = sum(s.get("avg_vote_score", 0) * s.get("games", 0) for s in summaries)
    skill = sum(s.get("avg_skill_score", 0) * s.get("games", 0) for s in summaries)
    confidence = sum(s.get("avg_confidence", 0) * s.get("games", 0) for s in summaries)
    calibration = merge_calibration_reports(summaries)
    fallback = sum(s.get("fallback_rate", 0) * s.get("games", 0) for s in summaries)
    vote_acc = sum(s.get("vote_accuracy", 0) * s.get("games", 0) for s in summaries)
    skill_acc = sum(s.get("skill_accuracy", 0) * s.get("games", 0) for s in summaries)
    policy_adj = sum(s.get("policy_adjusted_rate", 0) * s.get("games", 0) for s in summaries)
    bad_case = sum(s.get("bad_case_count", 0) * s.get("games", 0) for s in summaries)
    tp_quality = sum(s.get("turning_point_quality", 0) * s.get("games", 0) for s in summaries)
    info_score = sum(s.get("information_score", 0) * s.get("games", 0) for s in summaries)
    coop_score = sum(s.get("cooperation_score", 0) * s.get("games", 0) for s in summaries)
    # Merge by_role dicts: sum counts per role
    by_role: dict[str, dict] = {}
    for s in summaries:
        for role_name, role_data in s.get("by_role", {}).items():
            if role_name not in by_role:
                by_role[role_name] = dict(role_data)
            else:
                for k, v in role_data.items():
                    by_role[role_name][k] = by_role[role_name].get(k, 0) + v
    run_ids = [s.get("run_id", "") for s in summaries if s.get("run_id")]
    score_samples = _collect_samples(summaries, "score_samples", "avg_decision_score")
    role_weighted_samples = _collect_samples(summaries, "role_weighted_score_samples", "role_weighted_score")

    return LeaderboardEntry(
        version=entry_version,
        games=total_games,
        werewolf_win_rate=wolves / total_normal if total_normal else 0.0,
        villager_win_rate=villagers / total_normal if total_normal else 0.0,
        werewolf_win_rate_ci95=wilson_ci95(wolves, total_normal),
        villager_win_rate_ci95=wilson_ci95(villagers, total_normal),
        avg_days=avg_days / total_games if total_games else 0.0,
        avg_score=avg_score / total_games if total_games else 0.0,
        avg_score_ci95=mean_ci95(score_samples),
        role_weighted_score=role_weighted / total_games if total_games else 0.0,
        role_weighted_score_ci95=mean_ci95(role_weighted_samples),
        avg_speech_score=speech / total_games if total_games else 0.0,
        avg_vote_score=vote / total_games if total_games else 0.0,
        avg_skill_score=skill / total_games if total_games else 0.0,
        avg_confidence=confidence / total_games if total_games else 0.0,
        confidence_calibration_error=calibration["confidence_calibration_error"],
        confidence_calibration_count=calibration["confidence_calibration_count"],
        confidence_buckets=calibration["confidence_buckets"],
        fallback_rate=fallback / total_games if total_games else 0.0,
        vote_accuracy=vote_acc / total_games if total_games else 0.0,
        skill_accuracy=skill_acc / total_games if total_games else 0.0,
        policy_adjusted_rate=policy_adj / total_games if total_games else 0.0,
        bad_case_count=bad_case / total_games if total_games else 0.0,
        turning_point_quality=tp_quality / total_games if total_games else 0.0,
        information_score=info_score / total_games if total_games else 0.0,
        cooperation_score=coop_score / total_games if total_games else 0.0,
        by_role=by_role,
        run_ids=run_ids,
    )


def build_leaderboard(entries: list[LeaderboardEntry]) -> list[LeaderboardEntry]:
    """Sort entries by score descending and return as a list."""
    return sorted(entries, key=lambda e: e.role_weighted_score or e.avg_score, reverse=True)


def leaderboard_to_markdown(entries: list[LeaderboardEntry]) -> str:
    """Generate a compact leaderboard markdown table."""
    if not entries:
        return "# Leaderboard\n\nNo data."
    lines = [
        "# Agent 版本 Leaderboard",
        "",
        "| 版本 | 局数 | 狼人胜率 | 好人胜率 | 总分 | 角色加权 | 显著 | Fallback |",
        "|------|------|----------|----------|------|----------|------|----------|",
    ]
    for e in entries:
        lines.append(
            f"| {e.version} | {e.games} | {e.werewolf_win_rate:.1%} | {e.villager_win_rate:.1%} | "
            f"{e.avg_score:.1f} | {e.role_weighted_score:.1f} | "
            f"{'Y' if e.significant_vs_base else 'N'} | {e.fallback_rate:.1%} |"
        )
    lines.append("")
    return "\n".join(lines)


def leaderboard_detail_markdown(entries: list[LeaderboardEntry]) -> str:
    """Generate a detailed leaderboard markdown table with extra columns."""
    if not entries:
        return "# Leaderboard Detail\n\nNo data."
    lines = [
        "# Agent 版本 Leaderboard (详细)",
        "",
        "| 版本 | 局数 | 狼人胜率CI | 好人胜率CI | 平均天数 | 总分CI | 角色加权CI | 发言 | 投票 | 技能 | 投票准确率 | 技能准确率 | 置信度 | 校准误差 | Fallback | Policy修正 |",
        "|------|------|------------|------------|----------|--------|------------|------|------|------|------------|------------|--------|----------|----------|------------|",
    ]
    for e in entries:
        lines.append(
            f"| {e.version} | {e.games} | {_fmt_ci_pct(e.werewolf_win_rate, e.werewolf_win_rate_ci95)} | "
            f"{_fmt_ci_pct(e.villager_win_rate, e.villager_win_rate_ci95)} | "
            f"{e.avg_days:.1f} | {_fmt_ci(e.avg_score, e.avg_score_ci95)} | "
            f"{_fmt_ci(e.role_weighted_score, e.role_weighted_score_ci95)} | {e.avg_speech_score:.1f} | "
            f"{e.avg_vote_score:.1f} | {e.avg_skill_score:.1f} | "
            f"{e.vote_accuracy:.1%} | {e.skill_accuracy:.1%} | "
            f"{e.avg_confidence:.1%} | {e.confidence_calibration_error:.1%} | "
            f"{e.fallback_rate:.1%} | {e.policy_adjusted_rate:.1%} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_leaderboard(
    entries: list[LeaderboardEntry],
    output_dir: Path,
) -> None:
    """Write leaderboard JSON and markdown files to a directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    # JSON — list of entry dicts (atomic write)
    json_path = output_dir / "leaderboard.json"
    json_tmp = json_path.with_suffix(json_path.suffix + ".tmp")
    with open(json_tmp, "w", encoding="utf-8") as f:
        json.dump([e.to_dict() for e in entries], f, ensure_ascii=False, indent=2)
    os.replace(str(json_tmp), str(json_path))
    # Compact markdown
    with open(output_dir / "leaderboard.md", "w", encoding="utf-8") as f:
        f.write(leaderboard_to_markdown(entries))
    # Detail markdown
    with open(output_dir / "leaderboard_detail.md", "w", encoding="utf-8") as f:
        f.write(leaderboard_detail_markdown(entries))


def load_summaries_from_runs(run_dirs: list[Path]) -> list[dict]:
    """Load summary.json files from a list of run directories."""
    summaries: list[dict] = []
    for run_dir in run_dirs:
        summary_path = Path(run_dir) / "summary.json"
        if summary_path.exists():
            with open(summary_path, "r", encoding="utf-8") as f:
                summaries.append(json.load(f))
    return summaries


def _collect_samples(summaries: list[dict], sample_key: str, fallback_key: str) -> list[float]:
    samples: list[float] = []
    for summary in summaries:
        raw = summary.get(sample_key)
        if isinstance(raw, list):
            samples.extend(float(item) for item in raw if isinstance(item, int | float))
        elif summary.get("games", 0):
            samples.extend([float(summary.get(fallback_key, 0.0))] * int(summary.get("games", 0)))
    return samples


def _fmt_ci(value: float, ci: tuple[float, float]) -> str:
    return f"{value:.1f} [{ci[0]:.1f},{ci[1]:.1f}]"


def _fmt_ci_pct(value: float, ci: tuple[float, float]) -> str:
    return f"{value:.1%} [{ci[0]:.0%},{ci[1]:.0%}]"
