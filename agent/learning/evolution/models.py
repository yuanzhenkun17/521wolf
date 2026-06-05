"""Role evolution data models.

Dataclasses for the skill evolution pipeline: proposals, consolidations,
leaderboard entries, version history, and run tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent.common import beijing_now_iso
from agent.common.json import DictMixin
from agent.learning.pattern_engine import Pattern


# Enums
class EvolutionStatus(str, Enum):
    """Lifecycle states for an evolution run."""

    QUEUED = "queued"
    TRAINING = "training"
    CONSOLIDATING = "consolidating"
    APPLYING = "applying"
    BATTLING = "battling"
    REVIEWING = "reviewing"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    FAILED = "failed"


# Value objects
@dataclass(slots=True)
class EvidenceRef(DictMixin):
    """Reference to a specific game moment that supports a proposal."""

    game_id: str
    role: str
    player_id: int | None = None
    decision_id: str | None = None
    action_type: str | None = None
    quote: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceRef:
        return cls(
            game_id=str(data.get("game_id", "")),
            role=str(data.get("role", "")),
            player_id=int(data["player_id"]) if data.get("player_id") is not None else None,
            decision_id=data.get("decision_id"),
            action_type=data.get("action_type"),
            quote=data.get("quote"),
        )


@dataclass(slots=True)
class ScoredInsight(DictMixin):
    """A strategic insight extracted from game analysis with provenance."""

    text: str
    game_id: str
    relevance: str
    confidence: float
    source_roles: list[str] = field(default_factory=list)
    source_player_ids: list[int] = field(default_factory=list)
    source_decision_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoredInsight:
        return cls(
            text=str(data.get("text", "")),
            game_id=str(data.get("game_id", "")),
            relevance=str(data.get("relevance", "")),
            confidence=float(data.get("confidence", 0.0)),
            source_roles=[str(r) for r in data.get("source_roles", [])],
            source_player_ids=[int(p) for p in data.get("source_player_ids", [])],
            source_decision_ids=[str(d) for d in data.get("source_decision_ids", [])],
        )


# Version tracking
@dataclass(slots=True)
class RoleVersion(DictMixin):
    """Snapshot of a role's skill set at a point in time."""

    hash: str
    role: str
    skills: dict[str, str]
    created_at: str
    source: str
    parent_hash: str | None = None
    source_run_id: str | None = None
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoleVersion:
        return cls(
            hash=str(data.get("hash", "")),
            role=str(data.get("role", "")),
            skills={str(k): str(v) for k, v in data.get("skills", {}).items()},
            created_at=str(data.get("created_at", "")),
            source=str(data.get("source", "")),
            parent_hash=data.get("parent_hash"),
            source_run_id=data.get("source_run_id"),
            notes=[str(n) for n in data.get("notes", [])],
        )


@dataclass(slots=True)
class RoleHistory(DictMixin):
    """Ordered list of version hashes for a role."""

    role: str
    baseline: str
    versions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoleHistory:
        return cls(
            role=str(data.get("role", "")),
            baseline=str(data.get("baseline", "")),
            versions=[str(v) for v in data.get("versions", [])],
        )


@dataclass(slots=True)
class SkillVersionConfig(DictMixin):
    """Tracks which role version hash each skill file belongs to."""

    name: str
    created_at: str
    role_versions: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillVersionConfig:
        return cls(
            name=str(data.get("name", "")),
            created_at=str(data.get("created_at", "")),
            role_versions={str(k): str(v) for k, v in data.get("role_versions", {}).items()},
            notes=[str(n) for n in data.get("notes", [])],
        )


# Proposals and consolidation
@dataclass(slots=True)
class SkillProposal:
    """A single proposed change to a skill file."""

    proposal_id: str
    target_file: str
    action_type: str
    content: str
    rationale: str
    confidence: float
    risk: str
    expected_metric: str
    expected_direction: str
    section: str | None = None
    evidence: list[EvidenceRef] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    status: str = "proposed"

    # Hand-written to_dict: nested evidence items need explicit .to_dict()
    # calls; DictMixin handles nested dataclasses via to_jsonable but this
    # method also applies list() copies to mutable fields.
    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "target_file": self.target_file,
            "action_type": self.action_type,
            "content": self.content,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "risk": self.risk,
            "expected_metric": self.expected_metric,
            "expected_direction": self.expected_direction,
            "section": self.section,
            "evidence": [e.to_dict() for e in self.evidence],
            "conflicts_with": list(self.conflicts_with),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillProposal:
        return cls(
            proposal_id=str(data.get("proposal_id", "")),
            target_file=str(data.get("target_file", "")),
            action_type=str(data.get("action_type", "")),
            content=str(data.get("content", "")),
            rationale=str(data.get("rationale", "")),
            confidence=float(data.get("confidence", 0.0)),
            risk=str(data.get("risk", "")),
            expected_metric=str(data.get("expected_metric", "")),
            expected_direction=str(data.get("expected_direction", "")),
            section=data.get("section"),
            evidence=[EvidenceRef.from_dict(e) for e in data.get("evidence", [])],
            conflicts_with=[str(c) for c in data.get("conflicts_with", [])],
            status=str(data.get("status", "proposed")),
        )


@dataclass(slots=True)
class SkillConsolidation:
    """Batch of proposals produced by the LLM consolidator for a role.

    Unified from both the evolution-pipeline model (run_id, parent_hash,
    source_window, prompt_version) and the long-term-memory consolidator
    (raw_output, errors, to_markdown).  Optional fields default so either
    code-path can construct the class without friction.
    """

    role: str
    generated_at: str
    source_games: list[str] = field(default_factory=list)
    trends: list[str] = field(default_factory=list)
    proposals: list[SkillProposal] = field(default_factory=list)
    run_id: str = ""
    parent_hash: str = ""
    source_window: int = 0
    prompt_version: str = ""
    model_name: str | None = None
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)

    # Hand-written to_dict: nested proposals need explicit .to_dict() calls;
    # DictMixin handles nested dataclasses via to_jsonable but this method
    # also reorders fields and applies list() copies to mutable fields.
    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "run_id": self.run_id,
            "parent_hash": self.parent_hash,
            "generated_at": self.generated_at,
            "source_window": self.source_window,
            "prompt_version": self.prompt_version,
            "proposals": [p.to_dict() for p in self.proposals],
            "trends": list(self.trends),
            "source_games": list(self.source_games),
            "model_name": self.model_name,
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillConsolidation:
        return cls(
            role=str(data.get("role", "")),
            generated_at=str(data.get("generated_at", "")),
            source_games=[str(g) for g in data.get("source_games", [])],
            trends=[str(t) for t in data.get("trends", [])],
            proposals=[SkillProposal.from_dict(p) for p in data.get("proposals", [])],
            run_id=str(data.get("run_id", "")),
            parent_hash=str(data.get("parent_hash", "")),
            source_window=int(data.get("source_window", 0)),
            prompt_version=str(data.get("prompt_version", "")),
            model_name=data.get("model_name"),
            errors=[str(e) for e in data.get("errors", [])],
        )

    def to_markdown(self) -> str:
        """Render consolidation as a human-readable markdown report."""
        lines = [
            f"# Long-Term Consolidation: {self.role}",
            "",
            f"- Source games: {', '.join(self.source_games)}",
            f"- Generated: {self.generated_at}",
            "",
        ]
        if self.trends:
            lines.extend(["## Trends", ""])
            for t in self.trends:
                lines.append(f"- {t}")
            lines.append("")
        if self.proposals:
            lines.extend(["## Skill Proposals", ""])
            for p in self.proposals:
                lines.extend([
                    f"### {p.target_file}",
                    "",
                    f"- Action: {p.action_type}",
                    f"- Content: {p.content}",
                    f"- Risk: {p.risk or '-'}",
                    f"- Confidence: {p.confidence:.1%}",
                    "",
                ])
        if self.errors:
            lines.extend(["## Errors", ""])
            for e in self.errors:
                lines.append(f"- {e}")
        return "\n".join(lines).rstrip() + "\n"


@dataclass(slots=True)
class SkillDiff(DictMixin):
    """Before/after diff of a single skill file change."""

    filename: str
    action: str
    proposal_ref: str
    before: str | None = None
    after: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillDiff:
        return cls(
            filename=str(data.get("filename", "")),
            action=str(data.get("action", "")),
            proposal_ref=str(data.get("proposal_ref", "")),
            before=data.get("before"),
            after=data.get("after"),
        )


# Leaderboard
@dataclass(slots=True)
class RoleLeaderboardEntry:
    """Aggregated performance metrics for a role version across battles."""

    hash: str
    role: str
    battle_record: str
    recommendation: str
    is_baseline: bool = False
    total_games: int = 0
    target_role_role_weighted_score: float = 0.0
    target_role_speech_score: float = 0.0
    target_role_vote_score: float = 0.0
    target_role_skill_score: float = 0.0
    target_role_information_score: float = 0.0
    target_role_cooperation_score: float = 0.0
    target_role_fallback_rate: float = 0.0
    target_role_bad_case_rate: float = 0.0
    target_side_win_rate: float = 0.0
    target_side_win_rate_ci: tuple[float, float] = (0.0, 0.0)
    delta_vs_baseline: dict[str, float] = field(default_factory=dict)
    data_sufficient: bool = False

    # Hand-written to_dict: converts target_side_win_rate_ci tuple to list
    # for JSON serialization; DictMixin's to_jsonable does not convert tuples.
    def to_dict(self) -> dict[str, Any]:
        return {
            "hash": self.hash,
            "role": self.role,
            "battle_record": self.battle_record,
            "recommendation": self.recommendation,
            "is_baseline": self.is_baseline,
            "total_games": self.total_games,
            "target_role_role_weighted_score": self.target_role_role_weighted_score,
            "target_role_speech_score": self.target_role_speech_score,
            "target_role_vote_score": self.target_role_vote_score,
            "target_role_skill_score": self.target_role_skill_score,
            "target_role_information_score": self.target_role_information_score,
            "target_role_cooperation_score": self.target_role_cooperation_score,
            "target_role_fallback_rate": self.target_role_fallback_rate,
            "target_role_bad_case_rate": self.target_role_bad_case_rate,
            "target_side_win_rate": self.target_side_win_rate,
            "target_side_win_rate_ci": list(self.target_side_win_rate_ci),
            "delta_vs_baseline": dict(self.delta_vs_baseline),
            "data_sufficient": self.data_sufficient,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoleLeaderboardEntry:
        ci_raw = data.get("target_side_win_rate_ci", [0.0, 0.0])
        return cls(
            hash=str(data.get("hash", "")),
            role=str(data.get("role", "")),
            battle_record=str(data.get("battle_record", "")),
            recommendation=str(data.get("recommendation", "")),
            is_baseline=bool(data.get("is_baseline", False)),
            total_games=int(data.get("total_games", 0)),
            target_role_role_weighted_score=float(data.get("target_role_role_weighted_score", 0.0)),
            target_role_speech_score=float(data.get("target_role_speech_score", 0.0)),
            target_role_vote_score=float(data.get("target_role_vote_score", 0.0)),
            target_role_skill_score=float(data.get("target_role_skill_score", 0.0)),
            target_role_information_score=float(data.get("target_role_information_score", 0.0)),
            target_role_cooperation_score=float(data.get("target_role_cooperation_score", 0.0)),
            target_role_fallback_rate=float(data.get("target_role_fallback_rate", 0.0)),
            target_role_bad_case_rate=float(data.get("target_role_bad_case_rate", 0.0)),
            target_side_win_rate=float(data.get("target_side_win_rate", 0.0)),
            target_side_win_rate_ci=(float(ci_raw[0]), float(ci_raw[1])),
            delta_vs_baseline={str(k): float(v) for k, v in data.get("delta_vs_baseline", {}).items()},
            data_sufficient=bool(data.get("data_sufficient", False)),
        )


# Run tracking
@dataclass(slots=True)
class EvolutionRun:
    """Full state of a single evolution run for one role."""

    run_id: str
    role: str
    parent_hash: str
    status: str
    training_games: int = 0
    battle_games: int = 0
    baseline_config: SkillVersionConfig | None = None
    training_run_id: str | None = None
    training_output_dir: str | None = None
    candidate_hash: str | None = None
    battle_result: dict[str, Any] | None = None
    proposals: SkillConsolidation | None = None
    diff: list[SkillDiff] | None = None
    errors: list[str] = field(default_factory=list)

    # Hand-written to_dict: has nested .to_dict() calls for
    # baseline_config/proposals/diff and applies list() to mutable fields.
    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "role": self.role,
            "parent_hash": self.parent_hash,
            "status": self.status,
            "training_games": self.training_games,
            "battle_games": self.battle_games,
            "baseline_config": self.baseline_config.to_dict() if self.baseline_config is not None else None,
            "training_run_id": self.training_run_id,
            "training_output_dir": self.training_output_dir,
            "candidate_hash": self.candidate_hash,
            "battle_result": self.battle_result,
            "proposals": self.proposals.to_dict() if self.proposals is not None else None,
            "diff": [d.to_dict() for d in self.diff] if self.diff is not None else None,
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvolutionRun:
        proposals_raw = data.get("proposals")
        diff_raw = data.get("diff")
        baseline_config_raw = data.get("baseline_config")
        return cls(
            run_id=str(data.get("run_id", "")),
            role=str(data.get("role", "")),
            parent_hash=str(data.get("parent_hash", "")),
            status=str(data.get("status", "")),
            training_games=int(data.get("training_games", 0)),
            battle_games=int(data.get("battle_games", 0)),
            baseline_config=SkillVersionConfig.from_dict(baseline_config_raw)
            if baseline_config_raw is not None else None,
            training_run_id=data.get("training_run_id"),
            training_output_dir=data.get("training_output_dir"),
            candidate_hash=data.get("candidate_hash"),
            battle_result=data.get("battle_result"),
            proposals=SkillConsolidation.from_dict(proposals_raw) if proposals_raw is not None else None,
            diff=[SkillDiff.from_dict(d) for d in diff_raw] if diff_raw is not None else None,
            errors=[str(e) for e in data.get("errors", [])],
        )


# ---------------------------------------------------------------------------
# Knowledge versioning models (merged from agent.evolution.models)
# ---------------------------------------------------------------------------


@dataclass
class SkillFileRef:
    """Reference to a skill file on disk (path + content hash)."""
    path: str
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "content_hash": self.content_hash}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SkillFileRef:
        return cls(path=d["path"], content_hash=d["content_hash"])


@dataclass
class ProvenanceRecord:
    """Tracks where a version came from."""
    source: str  # seed, evolution, manual, rollback
    run_id: str | None = None
    proposal_ids: list[str] = field(default_factory=list)
    evidence_game_ids: list[str] = field(default_factory=list)
    rejected_pattern_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "run_id": self.run_id,
            "proposal_ids": self.proposal_ids,
            "evidence_game_ids": self.evidence_game_ids,
            "rejected_pattern_ids": self.rejected_pattern_ids,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProvenanceRecord:
        return cls(
            source=d.get("source", "unknown"),
            run_id=d.get("run_id"),
            proposal_ids=d.get("proposal_ids", []),
            evidence_game_ids=d.get("evidence_game_ids", []),
            rejected_pattern_ids=d.get("rejected_pattern_ids", []),
        )


@dataclass
class BattleMetrics:
    """Performance metrics from A/B battle."""
    win_rate: float = 0.0
    score: float = 0.0
    speech_score: float = 0.0
    vote_score: float = 0.0
    skill_score: float = 0.0
    games_played: int = 0
    confidence_interval: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "win_rate": self.win_rate,
            "score": self.score,
            "speech_score": self.speech_score,
            "vote_score": self.vote_score,
            "skill_score": self.skill_score,
            "games_played": self.games_played,
            "confidence_interval": list(self.confidence_interval) if self.confidence_interval else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BattleMetrics:
        ci = d.get("confidence_interval")
        return cls(
            win_rate=d.get("win_rate", 0.0),
            score=d.get("score", 0.0),
            speech_score=d.get("speech_score", 0.0),
            vote_score=d.get("vote_score", 0.0),
            skill_score=d.get("skill_score", 0.0),
            games_played=d.get("games_played", 0),
            confidence_interval=tuple(ci) if ci else None,
        )


@dataclass
class KnowledgePackage:
    """A versioned knowledge bundle for one role."""
    version_id: str
    role: str
    parent_id: str | None
    skills: list[SkillFileRef]
    patterns: list[dict[str, Any]]  # serialized Pattern dicts
    provenance: ProvenanceRecord
    metrics: BattleMetrics | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "role": self.role,
            "parent_id": self.parent_id,
            "skills": [s.to_dict() for s in self.skills],
            "patterns": self.patterns,
            "provenance": self.provenance.to_dict(),
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KnowledgePackage:
        return cls(
            version_id=d["version_id"],
            role=d["role"],
            parent_id=d.get("parent_id"),
            skills=[SkillFileRef.from_dict(s) for s in d.get("skills", [])],
            patterns=d.get("patterns", []),
            provenance=ProvenanceRecord.from_dict(d.get("provenance", {})),
            metrics=BattleMetrics.from_dict(d["metrics"]) if d.get("metrics") else None,
            created_at=d.get("created_at", ""),
        )


@dataclass
class VersionSummary:
    """Lightweight version info for listing."""
    version_id: str
    role: str
    source: str
    created_at: str
    is_baseline: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "role": self.role,
            "source": self.source,
            "created_at": self.created_at,
            "is_baseline": self.is_baseline,
        }


@dataclass
class KnowledgeDiff:
    """Diff between two KnowledgePackages."""
    skill_changes: list[dict[str, Any]]  # {file, action, before_lines, after_lines}
    patterns_added: list[dict[str, Any]]
    patterns_removed: list[dict[str, Any]]
    patterns_updated: list[dict[str, Any]]
    metrics_delta: dict[str, float] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_changes": self.skill_changes,
            "patterns_added": self.patterns_added,
            "patterns_removed": self.patterns_removed,
            "patterns_updated": self.patterns_updated,
            "metrics_delta": self.metrics_delta,
        }