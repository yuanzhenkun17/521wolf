"""Leaderboard — multi-version agent comparison across selfplay runs.

Aggregates results from multiple selfplay runs and produces
comparable metrics in JSON and markdown table formats.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


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
    avg_speech_score: float = 0.0
    avg_vote_score: float = 0.0
    avg_skill_score: float = 0.0
    avg_confidence: float = 0.0
    fallback_rate: float = 0.0
    vote_accuracy: float = 0.0
    skill_accuracy: float = 0.0
    policy_adjusted_rate: float = 0.0
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
            "avg_speech_score": round(self.avg_speech_score, 2),
            "avg_vote_score": round(self.avg_vote_score, 2),
            "avg_skill_score": round(self.avg_skill_score, 2),
            "avg_confidence": round(self.avg_confidence, 3),
            "fallback_rate": round(self.fallback_rate, 4),
            "vote_accuracy": round(self.vote_accuracy, 3),
            "skill_accuracy": round(self.skill_accuracy, 3),
            "policy_adjusted_rate": round(self.policy_adjusted_rate, 4),
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
    speech = sum(s.get("avg_speech_score", 0) * s.get("games", 0) for s in summaries)
    vote = sum(s.get("avg_vote_score", 0) * s.get("games", 0) for s in summaries)
    skill = sum(s.get("avg_skill_score", 0) * s.get("games", 0) for s in summaries)
    confidence = sum(s.get("avg_confidence", 0) * s.get("games", 0) for s in summaries)
    fallback = sum(s.get("fallback_rate", 0) * s.get("games", 0) for s in summaries)
    vote_acc = sum(s.get("vote_accuracy", 0) * s.get("games", 0) for s in summaries)
    skill_acc = sum(s.get("skill_accuracy", 0) * s.get("games", 0) for s in summaries)
    policy_adj = sum(s.get("policy_adjusted_rate", 0) * s.get("games", 0) for s in summaries)
    run_ids = [s.get("run_id", "") for s in summaries if s.get("run_id")]

    return LeaderboardEntry(
        version=entry_version,
        games=total_games,
        werewolf_win_rate=wolves / total_normal if total_normal else 0.0,
        villager_win_rate=villagers / total_normal if total_normal else 0.0,
        avg_days=avg_days / total_games if total_games else 0.0,
        avg_score=avg_score / total_games if total_games else 0.0,
        avg_speech_score=speech / total_games if total_games else 0.0,
        avg_vote_score=vote / total_games if total_games else 0.0,
        avg_skill_score=skill / total_games if total_games else 0.0,
        avg_confidence=confidence / total_games if total_games else 0.0,
        fallback_rate=fallback / total_games if total_games else 0.0,
        vote_accuracy=vote_acc / total_games if total_games else 0.0,
        skill_accuracy=skill_acc / total_games if total_games else 0.0,
        policy_adjusted_rate=policy_adj / total_games if total_games else 0.0,
        run_ids=run_ids,
    )


def build_leaderboard(entries: list[LeaderboardEntry]) -> list[LeaderboardEntry]:
    """Sort entries by score descending and return as a list."""
    return sorted(entries, key=lambda e: e.avg_score, reverse=True)


def leaderboard_to_markdown(entries: list[LeaderboardEntry]) -> str:
    """Generate a compact leaderboard markdown table."""
    if not entries:
        return "# Leaderboard\n\nNo data."
    lines = [
        "# Agent 版本 Leaderboard",
        "",
        "| 版本 | 局数 | 狼人胜率 | 好人胜率 | 总分 | 发言 | 投票 | 技能 | Fallback |",
        "|------|------|----------|----------|------|------|------|------|----------|",
    ]
    for e in entries:
        lines.append(
            f"| {e.version} | {e.games} | {e.werewolf_win_rate:.1%} | {e.villager_win_rate:.1%} | "
            f"{e.avg_score:.1f} | {e.avg_speech_score:.1f} | {e.avg_vote_score:.1f} | "
            f"{e.avg_skill_score:.1f} | {e.fallback_rate:.1%} |"
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
        "| 版本 | 局数 | 狼人胜率 | 好人胜率 | 平均天数 | 总分 | 发言 | 投票 | 技能 | 投票准确率 | 技能准确率 | 置信度 | Fallback | Policy修正 |",
        "|------|------|----------|----------|----------|------|------|------|------|------------|------------|--------|----------|------------|",
    ]
    for e in entries:
        lines.append(
            f"| {e.version} | {e.games} | {e.werewolf_win_rate:.1%} | {e.villager_win_rate:.1%} | "
            f"{e.avg_days:.1f} | {e.avg_score:.1f} | {e.avg_speech_score:.1f} | "
            f"{e.avg_vote_score:.1f} | {e.avg_skill_score:.1f} | "
            f"{e.vote_accuracy:.1%} | {e.skill_accuracy:.1%} | "
            f"{e.avg_confidence:.1%} | {e.fallback_rate:.1%} | {e.policy_adjusted_rate:.1%} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_leaderboard(
    entries: list[LeaderboardEntry],
    output_dir: Path,
) -> None:
    """Write leaderboard JSON and markdown files to a directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    # JSON — list of entry dicts
    with open(output_dir / "leaderboard.json", "w", encoding="utf-8") as f:
        json.dump([e.to_dict() for e in entries], f, ensure_ascii=False, indent=2)
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


# ── Wrapper class for version_battle compatibility ─────────────────────────


class Leaderboard:
    """Wrapper class around a list of entries.

    Used by version_battle.py which expects a Leaderboard-like object
    with .entries, __iter__, __getitem__, and to_dict().
    """

    def __init__(self, entries: list[LeaderboardEntry] | None = None) -> None:
        self.entries = list(entries) if entries else []

    def __iter__(self):
        return iter(self.entries)

    def __getitem__(self, index):
        return self.entries[index]

    def __len__(self):
        return len(self.entries)

    def add(self, entry: LeaderboardEntry) -> None:
        self.entries.append(entry)

    def to_dict(self) -> dict:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def to_markdown(self) -> str:
        return leaderboard_to_markdown(self.entries)

    def write_json(self, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def write_markdown(self, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())
