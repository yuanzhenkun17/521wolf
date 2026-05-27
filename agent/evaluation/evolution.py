"""Evolution pipeline — selfplay, analysis, candidate version, battle, verdict."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from agent.evaluation.leaderboard import LeaderboardEntry
from agent.evaluation.selfplay import SelfPlayConfig, SelfPlayResult, run_selfplay
from agent.evaluation.version_battle import (
    VersionBattleConfig,
    VersionBattleResult,
    run_version_battle,
    version_spec_from_manifest,
)
from agent.runtime.model import ModelAdapter
from agent.versioning.manifest import (
    VersionStatus,
    create_agent_version,
    evaluate_promotion,
    load_manifest,
    resolve_manifest_path,
    save_manifest,
    update_manifest_status,
)


RunSelfplayFunc = Callable[..., Awaitable[SelfPlayResult]]
RunVersionBattleFunc = Callable[..., Awaitable[VersionBattleResult]]


@dataclass(slots=True)
class EvolutionPipelineConfig:
    """Configuration for a one-shot self-evolution run."""

    base_version: str
    candidate_version: str
    training_games: int = 5
    battle_games: int = 20
    training_seed_start: int = 1
    battle_seed_start: int = 1001
    max_days: int = 20
    output_dir: Path = Path("runs/evolution")
    versions_root: Path = Path("agent_versions")
    enable_dream: bool = True
    enable_skill_proposals: bool = True
    auto_apply_skill_proposals: bool = True
    min_score_improvement: float = 0.05
    max_win_rate_drop: float = 0.10
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "base_version": self.base_version,
            "candidate_version": self.candidate_version,
            "training_games": self.training_games,
            "battle_games": self.battle_games,
            "training_seed_start": self.training_seed_start,
            "battle_seed_start": self.battle_seed_start,
            "max_days": self.max_days,
            "output_dir": str(self.output_dir),
            "versions_root": str(self.versions_root),
            "enable_dream": self.enable_dream,
            "enable_skill_proposals": self.enable_skill_proposals,
            "auto_apply_skill_proposals": self.auto_apply_skill_proposals,
            "min_score_improvement": self.min_score_improvement,
            "max_win_rate_drop": self.max_win_rate_drop,
            "notes": self.notes,
        }


@dataclass(slots=True)
class EvolutionPipelineResult:
    config: EvolutionPipelineConfig
    run_id: str
    output_dir: Path
    training_result: SelfPlayResult
    candidate_manifest_path: Path
    battle_result: VersionBattleResult
    promoted: bool
    reasons: list[str]
    metrics: dict[str, float]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "output_dir": str(self.output_dir),
            "config": self.config.to_dict(),
            "training": self.training_result.summary,
            "candidate_manifest_path": str(self.candidate_manifest_path),
            "battle": self.battle_result.to_dict(),
            "promoted": self.promoted,
            "reasons": self.reasons,
            "metrics": self.metrics,
        }


async def run_evolution_pipeline(
    config: EvolutionPipelineConfig,
    *,
    model: ModelAdapter | None = None,
    client_factory=None,
    selfplay_runner: RunSelfplayFunc = run_selfplay,
    battle_runner: RunVersionBattleFunc = run_version_battle,
) -> EvolutionPipelineResult:
    """Run one complete self-evolution iteration.

    The pipeline is intentionally auditable and conservative:
    selfplay writes review/experience/dream artifacts, candidate creation freezes
    skills and memory into ``agent_versions/<candidate>``, and the final verdict
    only updates manifest status.  Runtime code is never copied.
    """
    run_id = f"evolution_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    run_dir = config.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "config.json", config.to_dict())

    base_manifest_path = config.versions_root / config.base_version / "manifest.json"
    base_manifest = load_manifest(base_manifest_path)
    base_skill_dir = resolve_manifest_path(base_manifest_path, base_manifest.paths.skills)
    base_memory_dir = resolve_manifest_path(base_manifest_path, base_manifest.paths.memory)

    training_skill_dir = run_dir / "training_skills"
    if training_skill_dir.exists():
        shutil.rmtree(training_skill_dir)
    shutil.copytree(base_skill_dir, training_skill_dir)

    training_config = SelfPlayConfig(
        games=config.training_games,
        seed_start=config.training_seed_start,
        output_dir=run_dir / "training",
        agent_version=config.base_version,
        model_name=base_manifest.model.model or None,
        max_days=config.max_days,
        enable_review=True,
        enable_experience=True,
        enable_dream=False,
        enable_batch_dream=config.enable_dream,
        enable_skill_proposals=config.enable_skill_proposals,
        auto_apply_skill_proposals=config.auto_apply_skill_proposals,
        temperature=base_manifest.model.temperature,
        skill_dir=training_skill_dir,
    )
    training_result = await selfplay_runner(
        training_config,
        model=model,
        client_factory=client_factory,
    )

    training_run_dir = training_config.output_dir / training_result.run_id
    memory_candidate_dir = training_run_dir / "memory_candidate"
    source_memory_dir = memory_candidate_dir if memory_candidate_dir.exists() else base_memory_dir

    candidate_dir = create_agent_version(
        config.candidate_version,
        config.base_version,
        versions_root=config.versions_root,
        source_skill_dir=training_skill_dir,
        source_memory_dir=source_memory_dir,
        notes=config.notes or f"Generated by {run_id}",
    )
    candidate_manifest_path = candidate_dir / "manifest.json"
    candidate_manifest = load_manifest(candidate_manifest_path)
    candidate_manifest.training_source.update({
        "pipeline_run_id": run_id,
        "training_run_id": training_result.run_id,
        "training_output_dir": str(training_run_dir),
        "source_skill_dir": str(training_skill_dir),
        "source_memory_dir": str(source_memory_dir),
    })
    save_manifest(candidate_manifest, candidate_manifest_path)

    battle_config = VersionBattleConfig(
        versions=[
            version_spec_from_manifest(base_manifest_path),
            version_spec_from_manifest(candidate_manifest_path),
        ],
        games_per_version=config.battle_games,
        seed_start=config.battle_seed_start,
        output_dir=run_dir / "battle",
        max_days=config.max_days,
        enable_review=True,
        enable_experience=True,
    )
    battle_result = await battle_runner(
        battle_config,
        model=model,
        client_factory=client_factory,
    )

    base_entry = _find_entry(battle_result.leaderboard, base_manifest.display_name or base_manifest.version)
    candidate_entry = _find_entry(
        battle_result.leaderboard,
        candidate_manifest.display_name or candidate_manifest.version,
    )
    verdict = evaluate_promotion(
        candidate_entry,
        base_entry,
        min_score_improvement=config.min_score_improvement,
        max_win_rate_drop=config.max_win_rate_drop,
    )
    status = VersionStatus.VALIDATED if verdict.promoted else VersionStatus.REJECTED
    update_manifest_status(
        candidate_manifest_path,
        status,
        evaluation_update={
            "pipeline_run_id": run_id,
            "battle_output_dir": str(battle_result.output_dir),
            "promoted": verdict.promoted,
            "reasons": verdict.reasons,
            "metrics": verdict.metrics,
            "leaderboard": [entry.to_dict() for entry in battle_result.leaderboard],
        },
    )

    result = EvolutionPipelineResult(
        config=config,
        run_id=run_id,
        output_dir=run_dir,
        training_result=training_result,
        candidate_manifest_path=candidate_manifest_path,
        battle_result=battle_result,
        promoted=verdict.promoted,
        reasons=verdict.reasons,
        metrics=verdict.metrics,
    )
    _write_json(run_dir / "result.json", result.to_dict())
    return result


def _find_entry(entries: list[LeaderboardEntry], version: str) -> LeaderboardEntry:
    for entry in entries:
        if entry.version == version:
            return entry
    raise ValueError(f"leaderboard entry not found for version {version!r}")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
