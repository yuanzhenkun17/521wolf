"""Multi-version selfplay runner.

Runs multiple agent/skill/model versions over the same seed range and writes
a leaderboard that can be used for evaluation and presentation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from agent.runtime.model import ModelAdapter
from agent.evaluation.leaderboard import (
    LeaderboardEntry,
    aggregate_summaries,
    build_leaderboard,
    write_leaderboard,
)
from agent.evaluation.selfplay import SelfPlayConfig, SelfPlayResult, run_selfplay


RunSelfplayFunc = Callable[..., Awaitable[SelfPlayResult]]


@dataclass(slots=True)
class VersionSpec:
    """One comparable agent version."""

    name: str
    skill_dir: Path | None = None
    model_name: str | None = None
    temperature: float | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "skill_dir": str(self.skill_dir) if self.skill_dir else None,
            "model_name": self.model_name,
            "temperature": self.temperature,
            "notes": self.notes,
        }


@dataclass(slots=True)
class VersionBattleConfig:
    """Configuration for a multi-version comparison run."""

    versions: list[VersionSpec]
    games_per_version: int
    seed_start: int = 1
    output_dir: Path = Path("logs/version_battle")
    max_days: int = 20
    enable_review: bool = True
    enable_experience: bool = True

    def to_dict(self) -> dict:
        return {
            "versions": [v.to_dict() for v in self.versions],
            "games_per_version": self.games_per_version,
            "seed_start": self.seed_start,
            "output_dir": str(self.output_dir),
            "max_days": self.max_days,
            "enable_review": self.enable_review,
            "enable_experience": self.enable_experience,
        }


@dataclass(slots=True)
class VersionBattleResult:
    """Result of running all versions."""

    config: VersionBattleConfig
    runs: dict[str, SelfPlayResult]
    leaderboard: list[LeaderboardEntry]
    output_dir: Path

    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "runs": {
                name: result.summary
                for name, result in self.runs.items()
            },
            "leaderboard": [entry.to_dict() for entry in self.leaderboard],
            "output_dir": str(self.output_dir),
        }


async def run_version_battle(
    config: VersionBattleConfig,
    *,
    model: ModelAdapter | None = None,
    client_factory=None,
    runner: RunSelfplayFunc = run_selfplay,
) -> VersionBattleResult:
    """Run all versions with the same seed range and write a leaderboard."""
    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "version_battle_config.json").write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    runs: dict[str, SelfPlayResult] = {}
    entries: list[LeaderboardEntry] = []

    for version in config.versions:
        version_output_dir = config.output_dir / _safe_name(version.name)
        selfplay_config = SelfPlayConfig(
            games=config.games_per_version,
            seed_start=config.seed_start,
            output_dir=version_output_dir,
            agent_version=version.name,
            model_name=version.model_name,
            max_days=config.max_days,
            enable_review=config.enable_review,
            enable_experience=config.enable_experience,
            temperature=version.temperature if version.temperature is not None else 0.2,
            skill_dir=version.skill_dir,
        )

        result = await runner(
            selfplay_config,
            model=model,
            client_factory=client_factory,
        )
        runs[version.name] = result

        entry = aggregate_summaries([result.summary], version=version.name)
        entry.notes = version.notes
        entries.append(entry)

    leaderboard = build_leaderboard(entries)
    write_leaderboard(leaderboard, config.output_dir)

    battle_result = VersionBattleResult(
        config=config,
        runs=runs,
        leaderboard=leaderboard,
        output_dir=config.output_dir,
    )
    (config.output_dir / "version_battle_result.json").write_text(
        json.dumps(battle_result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return battle_result


def _safe_name(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)
    return safe or "version"
