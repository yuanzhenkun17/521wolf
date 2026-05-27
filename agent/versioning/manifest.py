"""Agent version manifest — load, save, validate.

Reference: docs/agent_version_management_plan.md Section 4
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from agent.evaluation.leaderboard import LeaderboardEntry


class VersionStatus(str, Enum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    REJECTED = "rejected"
    ARCHIVED = "archived"


@dataclass
class RuntimeConfig:
    git_commit: str = ""
    agent_runtime: str = "agent_v2"
    belief_policy: str = "weighted_evidence_v2"
    tot_enabled: bool = True
    got_enabled: bool = True
    got_trigger_policy: str = "sparse_high_conflict"
    got_trigger_threshold: float = 0.3

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> RuntimeConfig:
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class ModelConfig:
    provider: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    base_url: str = ""
    api_key: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> ModelConfig:
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class EvolutionConfig:
    per_game_dream_enabled: bool = False
    batch_dream_enabled: bool = True
    skill_proposal_policy: dict = field(default_factory=lambda: {
        "auto_apply": False,
        "min_confidence": 0.75,
        "min_evidence_cards": 3,
        "require_human_review": True,
    })

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> EvolutionConfig:
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class PathConfig:
    skills: str = "./skills"
    prompts: str = "./prompts"
    memory: str = "./memory"

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> PathConfig:
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class AgentVersionManifest:
    version: str
    display_name: str = ""
    description: str = ""
    created_at: str = ""
    base_version: str = ""
    status: VersionStatus = VersionStatus.DRAFT
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    evolution: EvolutionConfig = field(default_factory=EvolutionConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    training_source: dict = field(default_factory=dict)
    evaluation: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "display_name": self.display_name or self.version,
            "description": self.description,
            "created_at": self.created_at or datetime.now(timezone.utc).isoformat(),
            "base_version": self.base_version,
            "status": self.status.value,
            "runtime": self.runtime.to_dict(),
            "evolution": self.evolution.to_dict(),
            "model": self.model.to_dict(),
            "paths": self.paths.to_dict(),
            "training_source": self.training_source,
            "evaluation": self.evaluation,
            "notes": self.notes,
        }


def resolve_manifest_path(manifest_path: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (manifest_path.parent / path).resolve()
    base = manifest_path.parent.resolve()
    if not str(resolved).startswith(str(base)):
        raise ValueError(f"Path {raw} escapes manifest root {base}")
    return resolved


def load_manifest(path: Path) -> AgentVersionManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return AgentVersionManifest(
        version=data["version"],
        display_name=data.get("display_name", ""),
        description=data.get("description", ""),
        created_at=data.get("created_at", ""),
        base_version=data.get("base_version", ""),
        status=VersionStatus(data.get("status", "draft")),
        runtime=RuntimeConfig.from_dict(data.get("runtime", {})),
        evolution=EvolutionConfig.from_dict(data.get("evolution", {})),
        model=ModelConfig.from_dict(data.get("model", {})),
        paths=PathConfig.from_dict(data.get("paths", {})),
        training_source=data.get("training_source", {}),
        evaluation=data.get("evaluation", {}),
        notes=data.get("notes", []),
    )


def save_manifest(manifest: AgentVersionManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def current_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            cwd=Path(__file__).resolve().parent.parent.parent,
        ).strip()
    except Exception:
        return "unknown"


def validate_manifest(manifest: AgentVersionManifest, manifest_path: Path) -> list[str]:
    errors = []
    for field_name in ("skills", "memory"):
        raw = getattr(manifest.paths, field_name)
        resolved = resolve_manifest_path(manifest_path, raw)
        if not resolved.exists():
            errors.append(f"paths.{field_name} not found: {resolved}")
    return errors


def create_agent_version(
    name: str,
    base: str,
    *,
    versions_root: Path = Path("agent_versions"),
    source_skill_dir: Path | None = None,
    source_memory_dir: Path | None = None,
    notes: str = "",
) -> Path:
    base_dir = versions_root / base
    candidate_dir = versions_root / name
    if candidate_dir.exists():
        raise FileExistsError(f"Version {name} already exists at {candidate_dir}")
    base_manifest = load_manifest(base_dir / "manifest.json")
    src_skills = source_skill_dir or base_dir / "skills"
    if src_skills.exists():
        shutil.copytree(src_skills, candidate_dir / "skills")
    else:
        (candidate_dir / "skills").mkdir(parents=True)
    src_memory = source_memory_dir or base_dir / "memory"
    if src_memory.exists():
        shutil.copytree(src_memory, candidate_dir / "memory")
    else:
        (candidate_dir / "memory").mkdir(parents=True)
    manifest = AgentVersionManifest(
        version=name,
        base_version=base,
        status=VersionStatus.CANDIDATE,
        runtime=RuntimeConfig(git_commit=current_git_commit()),
        model=base_manifest.model,
        evolution=base_manifest.evolution,
        notes=[notes] if notes else [],
    )
    save_manifest(manifest, candidate_dir / "manifest.json")
    return candidate_dir


@dataclass
class PromotionVerdict:
    promoted: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


def evaluate_promotion(
    candidate: LeaderboardEntry,
    base: LeaderboardEntry,
    *,
    min_score_improvement: float = 0.05,
    max_win_rate_drop: float = 0.10,
) -> PromotionVerdict:
    reasons = []
    metrics = {}
    candidate_score = candidate.role_weighted_score or candidate.avg_score
    base_score = base.role_weighted_score or base.avg_score
    if base_score > 0:
        score_imp = (candidate_score - base_score) / base_score
    else:
        score_imp = 1.0 if candidate_score > 0 else 0.0
    metrics["score_improvement"] = score_imp
    metrics["candidate_score"] = candidate_score
    metrics["base_score"] = base_score
    if score_imp < min_score_improvement:
        reasons.append(f"score improvement {score_imp:.1%} < {min_score_improvement:.1%}")
    if (
        candidate.games >= 20
        and base.games >= 20
        and candidate.score_delta_vs_base != 0
        and not candidate.significant_vs_base
    ):
        reasons.append("score improvement is not statistically significant")
    if candidate.bad_case_count > base.bad_case_count:
        reasons.append(f"bad_case increased: {candidate.bad_case_count} > {base.bad_case_count}")
    if candidate.fallback_rate > base.fallback_rate:
        reasons.append(f"fallback_rate increased: {candidate.fallback_rate:.3f} > {base.fallback_rate:.3f}")
    if candidate.policy_adjusted_rate > base.policy_adjusted_rate:
        reasons.append(f"policy_adjusted_rate increased: {candidate.policy_adjusted_rate:.3f} > {base.policy_adjusted_rate:.3f}")
    win_drop = base.werewolf_win_rate - candidate.werewolf_win_rate
    metrics["win_rate_drop"] = win_drop
    if win_drop > max_win_rate_drop:
        reasons.append(f"win_rate drop {win_drop:.1%} > {max_win_rate_drop:.1%}")
    return PromotionVerdict(promoted=len(reasons) == 0, reasons=reasons, metrics=metrics)


def update_manifest_status(manifest_path: Path, status: VersionStatus, evaluation_update: dict | None = None) -> None:
    manifest = load_manifest(manifest_path)
    manifest.status = status
    if evaluation_update:
        manifest.evaluation.update(evaluation_update)
    save_manifest(manifest, manifest_path)


def rollback_version(current_validated: str, target: str, *, versions_root: Path = Path("agent_versions"), reason: str = "") -> None:
    versions_root = Path(versions_root)
    current_path = versions_root / current_validated / "manifest.json"
    target_path = versions_root / target / "manifest.json"

    # Pre-checks
    current_manifest = load_manifest(current_path)
    if current_manifest.status != VersionStatus.VALIDATED:
        raise ValueError(f"Current version '{current_validated}' is not VALIDATED (status={current_manifest.status})")
    target_manifest = load_manifest(target_path)  # noqa: F841 — validates target exists

    # Update target first (go-to state) — if this fails, current is still VALIDATED
    update_manifest_status(
        target_path,
        VersionStatus.VALIDATED,
        evaluation_update={"restored_from": current_validated, "rollback_reason": reason},
    )
    # Then archive current
    update_manifest_status(
        current_path,
        VersionStatus.ARCHIVED,
        evaluation_update={"rolled_back_to": target, "rollback_reason": reason},
    )
