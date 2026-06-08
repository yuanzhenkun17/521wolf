"""Evolution helpers — dedup, config, state, consolidation + apply logic.

Note: the actual LLM call lives in app/services/chain.py (consolidate_chain / apply_chain).
This module builds the prompts, parses the output, and validates the result — no LLM call here.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from enum import Enum

from app.util.json import compact_json, read_json_object, write_json
from app.util.manifest import build_run_manifest, write_manifest

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class EvolutionStatus(str, Enum):
    QUEUED = "queued"
    TRAINING = "training"
    CONSOLIDATING = "consolidating"
    APPLYING = "applying"
    BATTLING = "battling"
    REVIEWING = "reviewing"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Evolution models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SkillProposal:
    proposal_id: str = ""
    target_file: str = ""
    action_type: str = ""
    section: str = ""
    content: str = ""
    rationale: str = ""
    confidence: float = 0.0
    risk: str = "medium"
    expected_metric: str = ""
    expected_direction: str = "improve"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    status: str = "proposed"
    quality_score: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "target_file": self.target_file,
            "action_type": self.action_type,
            "section": self.section,
            "content": self.content,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "risk": self.risk,
            "expected_metric": self.expected_metric,
            "expected_direction": self.expected_direction,
            "evidence": self.evidence,
            "conflicts_with": self.conflicts_with,
            "status": self.status,
            "quality_score": dict(self.quality_score),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillProposal:
        if data is None:
            return cls()
        return cls(
            proposal_id=str(data.get("proposal_id", "")),
            target_file=str(data.get("target_file", "")),
            action_type=str(data.get("action_type", "")),
            section=str(data.get("section", "")),
            content=str(data.get("content", "")),
            rationale=str(data.get("rationale", "")),
            confidence=float(data.get("confidence", 0.0)),
            risk=str(data.get("risk", "medium")),
            expected_metric=str(data.get("expected_metric", "")),
            expected_direction=str(data.get("expected_direction", "improve")),
            evidence=[dict(e) for e in data.get("evidence", [])],
            conflicts_with=[str(c) for c in data.get("conflicts_with", [])],
            status=str(data.get("status", "proposed")),
            quality_score=dict(data.get("quality_score", {}) or {}),
        )


@dataclass(slots=True)
class SkillConsolidation:
    role: str = ""
    generated_at: str = ""
    source_games: list[str] = field(default_factory=list)
    trends: list[str] = field(default_factory=list)
    proposals: list[SkillProposal] = field(default_factory=list)
    run_id: str = ""
    parent_hash: str = ""
    source_window: int = 0
    prompt_version: str = ""
    model_name: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "generated_at": self.generated_at,
            "source_games": list(self.source_games),
            "trends": list(self.trends),
            "proposals": [p.to_dict() for p in self.proposals],
            "run_id": self.run_id,
            "parent_hash": self.parent_hash,
            "source_window": self.source_window,
            "prompt_version": self.prompt_version,
            "model_name": self.model_name,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillConsolidation:
        if data is None:
            return cls()
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
            warnings=[str(w) for w in data.get("warnings", [])],
            errors=[str(e) for e in data.get("errors", [])],
        )


@dataclass(slots=True)
class SkillDiff:
    filename: str
    action: str
    proposal_ref: str
    before: str | None = None
    after: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "action": self.action,
            "proposal_ref": self.proposal_ref,
            "before": self.before,
            "after": self.after,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillDiff:
        if data is None:
            return cls(filename="", action="", proposal_ref="")
        return cls(
            filename=str(data.get("filename", "")),
            action=str(data.get("action", "")),
            proposal_ref=str(data.get("proposal_ref", "")),
            before=data.get("before"),
            after=data.get("after"),
        )


@dataclass
class KnowledgeDiff:
    skill_changes: list[dict[str, Any]]
    metrics_delta: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_changes": self.skill_changes,
            "metrics_delta": self.metrics_delta,
        }


@dataclass(slots=True)
class EvolutionRun:
    run_id: str
    role: str
    parent_hash: str
    status: str
    training_games: int = 0
    battle_games: int = 0
    baseline_config: Any = None
    baseline_skill_dir: str | None = None
    training_run_id: str | None = None
    training_output_dir: str | None = None
    candidate_hash: str | None = None
    candidate_skill_dir: str | None = None
    battle_result: dict[str, Any] | None = None
    proposals: SkillConsolidation | None = None
    diff: list[SkillDiff] | None = None
    current_stage: str = ""
    progress: dict[str, Any] = field(default_factory=dict)
    last_heartbeat_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    manifest: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "role": self.role,
            "parent_hash": self.parent_hash,
            "status": self.status,
            "training_games": self.training_games,
            "battle_games": self.battle_games,
            "baseline_config": self.baseline_config.to_dict() if self.baseline_config is not None else None,
            "baseline_skill_dir": self.baseline_skill_dir,
            "training_run_id": self.training_run_id,
            "training_output_dir": self.training_output_dir,
            "candidate_hash": self.candidate_hash,
            "candidate_skill_dir": self.candidate_skill_dir,
            "battle_result": self.battle_result,
            "proposals": self.proposals.to_dict() if self.proposals is not None else None,
            "diff": [d.to_dict() for d in self.diff] if self.diff is not None else None,
            "current_stage": self.current_stage,
            "progress": dict(self.progress),
            "last_heartbeat_at": self.last_heartbeat_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "manifest": dict(self.manifest),
            "diagnostics": [dict(item) for item in self.diagnostics],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvolutionRun:
        if data is None:
            return cls(run_id="", role="", parent_hash="", status="")
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
            baseline_config=SkillVersionConfig.from_dict(baseline_config_raw) if baseline_config_raw is not None else None,
            baseline_skill_dir=data.get("baseline_skill_dir"),
            training_run_id=data.get("training_run_id"),
            training_output_dir=data.get("training_output_dir"),
            candidate_hash=data.get("candidate_hash"),
            candidate_skill_dir=data.get("candidate_skill_dir"),
            battle_result=data.get("battle_result"),
            proposals=SkillConsolidation.from_dict(proposals_raw) if proposals_raw is not None else None,
            diff=[SkillDiff.from_dict(d) for d in diff_raw] if diff_raw is not None else None,
            current_stage=str(data.get("current_stage", "")),
            progress=dict(data.get("progress", {}) or {}),
            last_heartbeat_at=data.get("last_heartbeat_at"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            manifest=dict(data.get("manifest", {}) or {}),
            diagnostics=[dict(item) for item in data.get("diagnostics", []) if isinstance(item, dict)],
            warnings=[str(w) for w in data.get("warnings", [])],
            errors=[str(e) for e in data.get("errors", [])],
        )


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def deduplicate_proposals(proposals: list[dict], rejected: list[dict]) -> list[dict]:
    """Remove proposals that overlap with previously rejected ones."""
    if not rejected:
        return proposals
    rejected_files = {r.get("target_file", "") for r in rejected}
    rejected_rationales = {r.get("rationale", "")[:80].lower() for r in rejected}

    def _is_dup(p: dict) -> bool:
        file = p.get("target_file", "")
        rationale = p.get("rationale", "")[:80].lower()
        return file in rejected_files or rationale in rejected_rationales

    return [p for p in proposals if not _is_dup(p)]


def score_proposal_quality(
    proposal: SkillProposal | dict[str, Any],
    raw: dict[str, Any] | None = None,
    *,
    rejected: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return deterministic quality factors for an evolve proposal."""
    if isinstance(proposal, SkillProposal):
        data = proposal.to_dict()
        evidence = proposal.evidence
    else:
        data = dict(proposal)
        evidence = [dict(e) for e in data.get("evidence", []) if isinstance(e, dict)]
    raw_data = dict(raw or data)
    game_ids = _proposal_source_game_ids(raw_data, evidence)
    risk = str(data.get("risk", "medium")).lower()
    duplicate_rejected = _proposal_matches_rejected(data, rejected or [])
    high_risk_fields = _proposal_high_risk_fields(data)
    evidence_count = len(evidence)
    covered_game_count = len(game_ids)

    score = 0.0
    score += min(evidence_count, 4) * 0.12
    score += min(covered_game_count, 4) * 0.12
    score += max(0.0, min(1.0, _as_float(data.get("confidence"), 0.0))) * 0.24
    score += {"low": 0.16, "medium": 0.08, "high": -0.20}.get(risk, 0.0)
    if duplicate_rejected:
        score -= 0.25
    if high_risk_fields:
        score -= min(0.30, 0.10 * len(high_risk_fields))
    score = max(0.0, min(1.0, score))

    return {
        "score": round(score, 3),
        "evidence_count": evidence_count,
        "covered_game_count": covered_game_count,
        "risk": risk,
        "duplicate_rejected": duplicate_rejected,
        "high_risk_fields": high_risk_fields,
    }


def annotate_proposal_quality(
    proposals: list[SkillProposal],
    *,
    rejected: list[dict[str, Any]] | None = None,
) -> None:
    """Attach deterministic quality_score to proposals in place."""
    for proposal in proposals:
        proposal.quality_score = score_proposal_quality(proposal, rejected=rejected)


# ---------------------------------------------------------------------------
# Evolution config
# ---------------------------------------------------------------------------

@dataclass
class EvolutionConfig:
    training_games: int = 20
    battle_games: int = 10
    role_concurrency: int = 2
    game_concurrency: int = 1
    llm_concurrency: int = 20
    llm_rpm: int = 60
    auto_promote: bool = False
    max_proposals: int = 3
    consolidation_window: int = 5
    prompt_version: str = "role_consolidation_v2"
    max_days: int = 20
    seed_start: int = 0
    # Battle seeds start high to avoid colliding with training seeds.
    battle_seed_start: int = 10_000
    # Promotion gate: candidate must beat baseline target-team win rate by this
    # absolute margin, and neither side may exceed the error-rate ceiling.
    promote_win_rate_margin: float = 0.10
    battle_error_rate_ceiling: float = 0.30
    battle_min_completed_games: int = 4
    battle_confidence_z: float = 1.96

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


# Defaults sourced from EvolutionConfig so the pipeline and config never drift.
_EVOLUTION_DEFAULTS = EvolutionConfig()


# ---------------------------------------------------------------------------
# Evolution state
# ---------------------------------------------------------------------------

class EvolutionStateManager:
    """Manages per-role evolution run state persistence."""

    def __init__(self, db_path: Path | str | None = None, root_dir: Path | str | None = None) -> None:
        if root_dir is not None:
            self._root_dir = Path(root_dir)
        elif db_path is not None:
            path = Path(db_path)
            self._root_dir = path if path.suffix == "" else path.parent / path.stem
        else:
            from app.config import DEFAULT_PATHS

            self._root_dir = DEFAULT_PATHS.evolution_dir
        self._root_dir.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        """Return the on-disk directory for an evolution run."""
        _validate_run_id(run_id)
        return self._root_dir / run_id

    def state_path(self, run_id: str) -> Path:
        """Return the state.json path for an evolution run."""
        return self.run_dir(run_id) / "state.json"

    def save_run(self, run: EvolutionRun) -> None:
        """Persist the current run state to JSON."""
        from app.util.time import beijing_now_iso

        state_path = self.state_path(run.run_id)
        existing = read_json_object(state_path, default={})
        payload = run.to_dict()
        updated_at = beijing_now_iso()
        payload["updated_at"] = updated_at
        terminal_statuses = {
            EvolutionStatus.PROMOTED.value,
            EvolutionStatus.REJECTED.value,
            EvolutionStatus.FAILED.value,
            EvolutionStatus.REVIEWING.value,
        }
        started_at = run.started_at or existing.get("started_at") or updated_at
        finished_at = run.finished_at or existing.get("finished_at")
        if not finished_at and str(run.status) in terminal_statuses:
            finished_at = updated_at
        manifest = run.manifest or build_run_manifest(
            run_type="evolve",
            run_id=run.run_id,
            model_config_hash="",
            seed=None,
            config={
                "role": run.role,
                "training_games": run.training_games,
                "battle_games": run.battle_games,
                "parent_hash": run.parent_hash,
                "baseline_config": run.baseline_config.to_dict()
                if run.baseline_config is not None and hasattr(run.baseline_config, "to_dict")
                else run.baseline_config,
            },
            started_at=started_at,
            finished_at=finished_at,
            status=run.status,
            error_summary="; ".join(str(item) for item in run.errors),
            paths={
                "run_dir": str(self.run_dir(run.run_id)),
                "state": "state.json",
                "manifest": "manifest.json",
                "baseline_skill_dir": run.baseline_skill_dir,
                "candidate_skill_dir": run.candidate_skill_dir,
                "training_output_dir": run.training_output_dir,
            },
            metadata={
                "role": run.role,
                "current_stage": run.current_stage,
                "progress": run.progress,
                "warnings": run.warnings,
                "diagnostics": run.diagnostics,
            },
        )
        payload["started_at"] = started_at
        payload["finished_at"] = finished_at
        payload["manifest"] = manifest
        write_manifest(self.run_dir(run.run_id) / "manifest.json", manifest)
        write_json(state_path, payload)

    def load_run(self, run_id: str) -> EvolutionRun | None:
        """Load a persisted run by id."""
        path = self.state_path(run_id)
        if not path.exists():
            return None
        try:
            return EvolutionRun.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            _log.warning("Skipping unreadable evolution run state %s: %s", path, exc)
            return None

    def list_runs(self, role: str) -> list[EvolutionRun]:
        """List persisted runs for a role, ordered by run id."""
        runs: list[EvolutionRun] = []
        if not self._root_dir.exists():
            return runs
        for state_path in sorted(self._root_dir.glob("*/state.json")):
            try:
                run = EvolutionRun.from_dict(json.loads(state_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if run.role == role:
                runs.append(run)
        return runs

    def scan_active_runs(self) -> list[EvolutionRun]:
        """Return non-terminal runs for recovery dashboards."""
        terminal = {
            EvolutionStatus.PROMOTED.value,
            EvolutionStatus.REJECTED.value,
            EvolutionStatus.FAILED.value,
        }
        active: list[EvolutionRun] = []
        for state_path in sorted(self._root_dir.glob("*/state.json")):
            try:
                run = EvolutionRun.from_dict(json.loads(state_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if str(run.status) not in terminal:
                active.append(run)
        return active


_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def normalize_run_id(run_id: Any, *, default: str | None = None) -> str:
    """Return a normalized, path-safe evolution run id or raise ValueError."""
    text = str(run_id if run_id is not None else "").strip()
    if not text and default is not None:
        text = str(default).strip()
    _validate_run_id(text)
    return text


def _validate_run_id(run_id: str) -> None:
    if not run_id or not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"Unsafe run_id: {run_id!r}")


# Forward reference — avoids circular import
from app.lib.version import SkillVersionConfig


# ---------------------------------------------------------------------------
# Consolidation — build prompt messages + parse output
# (LLM call itself happens in app/services/chain.py:consolidate_chain)
# ---------------------------------------------------------------------------

CONSOLIDATION_PROMPT_VERSION = "role_consolidation_app_v1"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def summarize_training_game(game: dict[str, Any], role: str) -> dict[str, Any]:
    """Reduce a raw training-game result to the role-relevant signal the LLM needs."""
    summary: dict[str, Any] = {
        "game_id": game.get("game_id"),
        "winner": game.get("winner"),
        "days": game.get("days"),
    }
    evidence_summary = _summarize_evidence_for_role(game, role)
    if evidence_summary:
        summary.update(evidence_summary)
        return summary

    roles = game.get("player_roles", {}) or {}
    role_players = {
        str(pid) for pid, r in roles.items() if str(r) == role
    }
    decisions = [
        {
            "player_id": d.get("player_id"),
            "action_type": d.get("action_type"),
            "action": d.get("action"),
            "reasoning": (d.get("private_reasoning") or d.get("reasoning") or "")[:240],
            "confidence": d.get("confidence"),
        }
        for d in game.get("decisions", [])
        if isinstance(d, dict)
        and (not role_players or str(d.get("player_id")) in role_players)
    ]
    summary["role_decisions"] = decisions[:12]
    return summary


def _summarize_evidence_for_role(game: dict[str, Any], role: str) -> dict[str, Any]:
    """Extract compact role-relevant key decisions from training evidence."""
    evidence = game.get("evidence")
    if not isinstance(evidence, dict):
        return {}

    role_key_decisions = _dict_items(evidence.get("role_key_decisions"))
    if not role_key_decisions:
        all_key_decisions = _dict_items(evidence.get("key_decisions"))
        role_key_decisions = [
            item for item in all_key_decisions
            if not role or str(item.get("role") or "") == role
        ] or all_key_decisions
    if not role_key_decisions:
        return {}

    result: dict[str, Any] = {
        "key_decisions": [_compact_training_key_decision(item) for item in role_key_decisions[:8]],
    }
    counts = evidence.get("counts")
    if isinstance(counts, dict):
        result["evidence_counts"] = {
            "decisions": counts.get("decisions"),
            "key_decisions": counts.get("key_decisions"),
            "role_key_decisions": counts.get("role_key_decisions"),
        }
    return result


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _compact_training_key_decision(item: dict[str, Any]) -> dict[str, Any]:
    quote = str(item.get("reason") or item.get("public_text") or "")[:180]
    return {
        "decision_id": item.get("decision_id"),
        "day": item.get("day"),
        "phase": item.get("phase"),
        "action_type": item.get("action_type"),
        "player_id": item.get("player_id"),
        "role": item.get("role"),
        "target": item.get("target"),
        "choice": item.get("choice"),
        "impact_level": item.get("impact_level"),
        "key_reason": item.get("key_reason"),
        "quote": quote,
        "notes": item.get("notes", []),
    }


def build_consolidation_messages(
    *,
    role: str,
    training_games: list[dict[str, Any]],
    skills_inventory: str,
    modifiable_files: list[dict[str, Any]],
    rejected: list[dict[str, Any]] | None = None,
    max_proposals: int = 3,
) -> list[dict[str, str]]:
    """Build the LLM messages for role-level skill consolidation."""
    summaries = [summarize_training_game(g, role) for g in training_games if not g.get("error")]
    rejected_text = _format_rejected_buffer(rejected or [])
    return [
        {
            "role": "system",
            "content": (
                "你是狼人杀 Agent 的角色级长期记忆整合器。"
                "你需要分析某角色最近 N 局自我对弈的关键决策证据，发现该角色的跨局趋势，并提出 skill 修改建议。"
                "训练摘要中的 key_decisions 是优先证据来源。"
                "每条建议必须有证据支撑，至少引用 2 个不同 game_id。必须输出 JSON，不要输出额外自然语言。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"分析角色: {role}\n\n"
                f"最近 {len(summaries)} 局训练对弈摘要（优先包含按角色过滤的 key_decisions）:\n"
                f"{compact_json(summaries)}\n\n"
                f"当前角色 skills:\n{skills_inventory}\n\n"
                f"可修改文件清单(JSON): {compact_json(modifiable_files)}\n"
                f"{rejected_text}\n"
                "请分析跨局趋势并提出 skill 修改建议，要求:\n"
                "1. trends: 3-5 条跨局趋势\n"
                f"2. proposals: 最多 {max_proposals} 个最重要的修改，每条只表达一个可验证的行为变化\n"
                "   - target_file 必须从上方可修改文件清单逐字复制；新建用 action_type=create_skill\n"
                "   - action_type ∈ append_rule|rewrite_section|deprecate_rule|create_skill\n"
                "   - 已有文件只能使用其 evolution.allowed_actions 内的动作\n"
                "   - risk ∈ low|medium|high；high risk 只写入 trends，不进 proposals\n"
                "   - expected_direction ∈ improve|maintain|reduce\n"
                "   - 每个 proposal 至少引用 2 个不同 game_id 作为 evidence；若摘要含 key_decisions，"
                "evidence 必须带 decision_id、action_type 和 quote\n"
                "   - 不要把多个规则打包进同一个 proposal\n\n"
                "输出 JSON schema:\n"
                "{\n"
                '  "trends": ["趋势1", "趋势2"],\n'
                '  "proposals": [\n'
                "    {\n"
                '      "proposal_id": "prop_001",\n'
                '      "target_file": "从清单逐字复制.md",\n'
                '      "action_type": "append_rule|rewrite_section|deprecate_rule|create_skill",\n'
                '      "section": "目标章节(rewrite_section时必填)",\n'
                '      "content": "具体修改内容",\n'
                '      "rationale": "修改理由",\n'
                '      "confidence": 0.0,\n'
                '      "risk": "low|medium|high",\n'
                '      "expected_metric": "期望影响的指标",\n'
                '      "expected_direction": "improve|maintain|reduce",\n'
                '      "evidence": [{"game_id": "g1", "decision_id": "d1", "action_type": "exile_vote", "quote": "原文摘录"}],\n'
                '      "conflicts_with": []\n'
                "    }\n"
                "  ]\n"
                "}"
            ),
        },
    ]


def _format_rejected_buffer(rejected: list[dict[str, Any]]) -> str:
    """Format previously rejected proposals so the LLM avoids repeating them."""
    if not rejected:
        return ""
    lines = ["## 近期被拒绝的提案（避免重复方向）", ""]
    for i, r in enumerate(rejected, 1):
        lines.append(
            f"{i}. **{r.get('target_file', '?')}** ({r.get('action_type', '?')}) "
            f"— {str(r.get('rationale', '无理由'))[:120]}"
        )
    return "\n".join(lines)


def parse_consolidation(
    *,
    role: str,
    raw_output: str,
    run_id: str = "",
    parent_hash: str = "",
    source_games: list[str] | None = None,
    source_window: int = 0,
    max_proposals: int = 3,
    prompt_version: str = CONSOLIDATION_PROMPT_VERSION,
) -> SkillConsolidation:
    """Parse raw LLM output into a SkillConsolidation. Never raises."""
    from app.util.text import extract_json
    from app.util.time import beijing_now_iso

    data: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []
    raw_text = str(raw_output or "")
    try:
        parsed = extract_json(raw_text)
        if isinstance(parsed, dict):
            data = parsed
        else:
            errors.append("consolidate: LLM JSON root must be an object")
    except ValueError as exc:
        errors.append(f"consolidate: failed to parse LLM JSON: {exc}")

    proposals_raw: list[Any] = []
    if "proposals" not in data:
        errors.append("consolidate: missing proposals list in LLM output")
    elif not isinstance(data.get("proposals"), list):
        errors.append("consolidate: proposals must be a list")
    else:
        proposals_raw = list(data.get("proposals") or [])

    proposals: list[SkillProposal] = []
    for i, p in enumerate(proposals_raw):
        if not isinstance(p, dict):
            warnings.append(f"consolidate: dropped proposal #{i + 1}: proposal must be an object")
            continue
        evidence = [dict(e) for e in p.get("evidence", []) if isinstance(e, dict)]
        proposal = SkillProposal(
            proposal_id=str(p.get("proposal_id", "") or f"{run_id or 'run'}_prop_{i + 1:03d}"),
            target_file=str(p.get("target_file", "")),
            action_type=str(p.get("action_type", "")),
            section=str(p.get("section", "")),
            content=str(p.get("content", "")),
            rationale=str(p.get("rationale", "")),
            confidence=_as_float(p.get("confidence"), 0.0),
            risk=str(p.get("risk", "medium")),
            expected_metric=str(p.get("expected_metric", "")),
            expected_direction=str(p.get("expected_direction", "improve")),
            evidence=evidence,
            conflicts_with=[str(c) for c in p.get("conflicts_with", [])],
            status="proposed",
        )
        proposal.quality_score = score_proposal_quality(proposal, raw=p)
        validation_errors = _validate_consolidation_proposal(proposal, p)
        if validation_errors:
            warnings.append(
                f"consolidate: dropped proposal {proposal.proposal_id or f'#{i + 1}'}: "
                + "; ".join(validation_errors)
            )
            continue
        proposals.append(proposal)

    trends_raw = data.get("trends", [])
    trends = [str(t) for t in trends_raw][:5] if isinstance(trends_raw, list) else []
    return SkillConsolidation(
        role=role,
        run_id=run_id,
        parent_hash=parent_hash,
        generated_at=beijing_now_iso(),
        source_games=list(source_games or []),
        source_window=source_window,
        prompt_version=prompt_version,
        trends=trends,
        proposals=proposals[:max_proposals],
        warnings=warnings,
        errors=errors,
    )


def _validate_consolidation_proposal(
    proposal: SkillProposal,
    raw: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for field_name in ("target_file", "action_type", "content", "rationale"):
        if not str(getattr(proposal, field_name, "")).strip():
            errors.append(f"missing {field_name}")
    source_game_ids = _proposal_source_game_ids(raw, proposal.evidence)
    if len(source_game_ids) < 2:
        errors.append("requires evidence from at least 2 distinct game_id values")
    return errors


def _proposal_source_game_ids(raw: dict[str, Any], evidence: list[dict[str, Any]]) -> set[str]:
    game_ids: set[str] = set()
    for item in evidence:
        game_id = item.get("game_id") or item.get("source_game") or item.get("source_game_id")
        if game_id:
            game_ids.add(str(game_id))
    for key in ("source_games", "source_game_ids", "game_ids"):
        values = raw.get(key)
        if isinstance(values, list):
            for value in values:
                if value:
                    game_ids.add(str(value))
    return game_ids


def _proposal_matches_rejected(proposal: dict[str, Any], rejected: list[dict[str, Any]]) -> bool:
    target_file = str(proposal.get("target_file", ""))
    action_type = str(proposal.get("action_type", ""))
    rationale = str(proposal.get("rationale", ""))[:80].lower()
    content_hash = _short_text_hash(str(proposal.get("content", "")))
    for item in rejected:
        if not isinstance(item, dict):
            continue
        same_target = target_file and target_file == str(item.get("target_file", ""))
        same_action = not action_type or not item.get("action_type") or action_type == str(item.get("action_type", ""))
        item_rationale = str(item.get("rationale", ""))[:80].lower()
        item_content_hash = _short_text_hash(str(item.get("content", "")))
        if same_target and same_action and (rationale == item_rationale or content_hash == item_content_hash):
            return True
    return False


def _proposal_high_risk_fields(proposal: dict[str, Any]) -> list[str]:
    target = str(proposal.get("target_file", "")).lower()
    content = str(proposal.get("content", "")).lower()
    section = str(proposal.get("section", "")).lower()
    fields: list[str] = []
    checks = {
        "role_identity": ("role", "identity", "身份", "阵营"),
        "private_info": ("private", "hidden", "上帝", "私有", "夜晚"),
        "front_matter": ("front matter", "yaml", "evolution:", "applicable_actions"),
        "global_policy": ("global", "system", "all roles", "所有角色"),
    }
    haystack = "\n".join([target, content, section])
    for name, needles in checks.items():
        if any(needle in haystack for needle in needles):
            fields.append(name)
    return fields


def _short_text_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def format_skill_inventory(skills: list[Any]) -> str:
    """Format MarkdownSkill objects with evolution constraints for the LLM."""
    if not skills:
        return "(no skills found)"
    parts: list[str] = []
    for skill in skills:
        actions = sorted(a.value for a in getattr(skill, "applicable_actions", set()))
        evolution = skill.evolution if isinstance(getattr(skill, "evolution", None), dict) else {}
        allowed = [str(a) for a in evolution.get("allowed_actions", [])]
        role_val = skill.role.value if getattr(skill, "role", None) is not None else "common"
        parts.extend([
            f"## Skill file: {skill.relative_path or skill.name}",
            f"name: {skill.name}",
            f"role: {role_val}",
            f"applicable_actions: {compact_json(actions)}",
            f"evolution.enabled: {bool(evolution.get('enabled', False))}",
            f"evolution.allowed_actions: {compact_json(allowed)}",
            "body:",
            (skill.body or "")[:1200],
            "",
        ])
    return "\n".join(parts).strip()


def modifiable_skill_files(skills: list[Any]) -> list[dict[str, Any]]:
    """Return the subset of files the applier may legally modify."""
    result: list[dict[str, Any]] = []
    for skill in skills:
        evolution = skill.evolution if isinstance(getattr(skill, "evolution", None), dict) else {}
        allowed = [str(a) for a in evolution.get("allowed_actions", [])]
        if not evolution.get("enabled") or not allowed:
            continue
        result.append({
            "target_file": skill.relative_path or skill.name,
            "name": skill.name,
            "role": skill.role.value if getattr(skill, "role", None) is not None else "common",
            "allowed_actions": allowed,
        })
    return result


# ---------------------------------------------------------------------------
# Applier — turn approved proposals into new skill file contents + diffs.
# (LLM call itself happens in app/services/chain.py:apply_chain via the
#  ``apply_fn`` callback passed in by the node.)
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 0.5
MAX_SKILL_LENGTH = 5000
MAX_CHANGED_FILES = 5
MAX_ACTIVE_SKILLS_PER_ROLE = 6
CREATE_SKILL_ACTION = "create_skill"

GLOBAL_ALLOWED_PROPOSAL_ACTIONS = {
    "append_rule",
    "rewrite_section",
    "deprecate_rule",
    CREATE_SKILL_ACTION,
}
GLOBAL_ALLOWED_MODIFY_ACTIONS = GLOBAL_ALLOWED_PROPOSAL_ACTIONS - {CREATE_SKILL_ACTION}
_CREATE_SKILL_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,48}$")
_SLOW_UPDATE_PATTERN = re.compile(
    r"<!--\s*slow_update\s*-->(.*?)<!--\s*/slow_update\s*-->",
    re.DOTALL,
)


async def apply_proposals(
    current_skills: dict[str, str],
    consolidation: SkillConsolidation,
    apply_fn: Any,
) -> tuple[dict[str, str], list[SkillDiff]]:
    """Apply eligible proposals to skill files via an LLM ``apply_fn``.

    ``apply_fn`` is an async callable ``(messages) -> str`` — the node passes a
    bound ``run_apply_chain`` so the only LLM call stays in services/chain.py.
    On any unrecoverable error the original skills are returned with an empty
    diff list (graceful degradation — never breaks the pipeline).
    """
    eligible = _filter_eligible(consolidation.proposals)
    if not eligible:
        _record_apply_error(consolidation, "apply: no eligible proposals after filtering")
        _log.info("apply: no eligible proposals after filtering")
        return dict(current_skills), []

    eligible = _resolve_conflicts(eligible)
    active = [p for p in eligible if p.status == "proposed"]
    if not active:
        _record_apply_error(consolidation, "apply: all proposals skipped after conflict resolution")
        _log.info("apply: all proposals skipped after conflict resolution")
        return dict(current_skills), []
    if len(active) > MAX_CHANGED_FILES:
        _log.warning("apply: too many proposals (%d), keeping first %d", len(active), MAX_CHANGED_FILES)
        active = active[:MAX_CHANGED_FILES]

    messages = _build_apply_messages(current_skills, active, consolidation.role)
    try:
        raw = await apply_fn(messages)
    except Exception as exc:
        _record_apply_error(consolidation, f"apply: LLM call failed: {exc}")
        _log.exception("apply: LLM call failed")
        return dict(current_skills), []

    try:
        parsed = _parse_apply_output(raw)
    except ValueError as exc:
        _record_apply_error(consolidation, f"apply: failed to parse LLM output: {exc}")
        _log.error("apply: failed to parse LLM output: %s", exc)
        return dict(current_skills), []

    proposed_files: dict[str, str] = parsed.get("files", {})
    changes: list[dict[str, str]] = parsed.get("changes", [])

    errors = _validate_all(current_skills, proposed_files, active, consolidation.role)
    if errors:
        for err in errors:
            _record_apply_error(consolidation, f"apply: validation failed: {err}")
            _log.error("apply: validation failed: %s", err)
        return dict(current_skills), []

    ok, smoke_err = _smoke_test(proposed_files)
    if not ok:
        _record_apply_error(consolidation, f"apply: smoke test failed: {smoke_err}")
        _log.error("apply: smoke test failed: %s", smoke_err)
        return dict(current_skills), []

    diffs = _build_diffs(current_skills, proposed_files, changes, active)
    _log.info("apply: applied %d proposals, %d files changed", len(active), len(diffs))
    return proposed_files, diffs


def _record_apply_error(consolidation: SkillConsolidation, message: str) -> None:
    if message not in consolidation.errors:
        consolidation.errors.append(message)


def _filter_eligible(proposals: list[SkillProposal]) -> list[SkillProposal]:
    """Keep confidence >= threshold, risk != high, status == proposed."""
    eligible: list[SkillProposal] = []
    for p in proposals:
        if p.status != "proposed":
            continue
        if p.confidence < CONFIDENCE_THRESHOLD:
            continue
        if p.risk == "high":
            continue
        eligible.append(p)
    return eligible


def _resolve_conflicts(proposals: list[SkillProposal]) -> list[SkillProposal]:
    """If A conflicts_with B, skip both. Returns a new list (no input mutation)."""
    import copy

    by_id = {p.proposal_id: p for p in proposals}
    skip_ids: set[str] = set()
    for p in proposals:
        for conflict_id in p.conflicts_with:
            if conflict_id in by_id:
                skip_ids.add(p.proposal_id)
                skip_ids.add(conflict_id)
    result: list[SkillProposal] = []
    for p in proposals:
        if p.proposal_id in skip_ids:
            skipped = copy.deepcopy(p)
            skipped.status = "skipped"
            result.append(skipped)
        else:
            result.append(p)
    return result


def _build_apply_messages(
    current_skills: dict[str, str],
    eligible: list[SkillProposal],
    role: str,
) -> list[dict[str, str]]:
    """Build the prompt asking the LLM to produce the modified skill files."""
    parts: list[str] = [
        "You are a skill-file editor for a Werewolf game AI agent. "
        "Apply the atomic rule proposals below to the current skill files. "
        "Return ONLY a JSON object with the exact shape:\n"
        '{"files": {"filename.md": "full file content", ...}, '
        '"changes": [{"filename": "file.md", "action": "modified|created", "description": "brief"}]}\n',
        f"\nRole: {role}\n",
        "Rules:\n"
        "- Existing files may only be modified when targeted by an eligible proposal.\n"
        f"- New files may only be created by action_type={CREATE_SKILL_ACTION}, named '<slug>.md'.\n"
        "- Return every existing file in files, unchanged unless targeted.\n"
        "- Do not change front-matter role/name/applicable_actions/evolution for existing files.\n"
        "- Preserve any <!-- slow_update -->...<!-- /slow_update --> region content exactly "
        "(you may append inside it, but must not delete or alter existing content).\n",
        "## Current skill files\n",
    ]
    if current_skills:
        for fname, content in current_skills.items():
            parts.append(f"### {fname}\n```\n{content}\n```\n")
    else:
        parts.append("(empty baseline: no current skill files)\n")
    parts.append("## Proposals to apply\n")
    for p in eligible:
        parts.append(
            f"- **{p.proposal_id}** (action={p.action_type}, target={p.target_file}, "
            f"confidence={p.confidence:.2f})\n  rationale: {p.rationale}\n  content: {p.content}\n"
        )
        if p.section:
            parts.append(f"  section: {p.section}\n")
    parts.append("\nReturn the JSON object now. Do NOT add commentary outside the JSON.")
    return [{"role": "user", "content": "\n".join(parts)}]


def _parse_apply_output(raw: str) -> dict[str, Any]:
    """Parse the LLM JSON response. Raises ValueError on bad/empty/missing-files JSON."""
    from app.util.text import extract_json

    data = extract_json(str(raw or ""))
    if not isinstance(data, dict):
        raise ValueError("LLM output is not a JSON object")
    if "files" not in data or not isinstance(data["files"], dict):
        raise ValueError("LLM output missing 'files' object")
    return data


def _validate_all(
    current_skills: dict[str, str],
    proposed_files: dict[str, str],
    eligible: list[SkillProposal],
    role: str,
) -> list[str]:
    """Run safety checks. Returns a list of error strings (empty = pass)."""
    from app.services.prompt import parse_front_matter
    from app.util.action_types import AGENT_ACTION_TYPES
    from engine import Role
    from storage.interfaces import normalize_skill_path, normalize_skill_text

    errors: list[str] = []
    valid_roles = {r.value for r in Role}
    eligible_targets = {p.target_file for p in eligible}
    create_targets = {p.target_file for p in eligible if p.action_type == CREATE_SKILL_ACTION}

    def _path_safe(path: str) -> str | None:
        try:
            normalize_skill_path(path)
        except ValueError as exc:
            return f"Path '{path}' is unsafe: {exc}"
        return None

    # 1. Only modify/create files targeted by an eligible proposal.
    for fname, new_content in proposed_files.items():
        if (err := _path_safe(fname)):
            errors.append(err)
        old_content = current_skills.get(fname)
        if fname in eligible_targets:
            continue
        if old_content is None:
            errors.append(f"File '{fname}' created without an eligible proposal")
        elif normalize_skill_text(old_content) != normalize_skill_text(new_content):
            errors.append(f"File '{fname}' modified without an eligible proposal")

    # 1b. Proposal action_type against whitelist + per-skill allowed_actions.
    for p in eligible:
        if (err := _path_safe(p.target_file)):
            errors.append(f"[{p.target_file}] {err}")
        if p.action_type not in GLOBAL_ALLOWED_PROPOSAL_ACTIONS:
            errors.append(f"[{p.target_file}] action_type '{p.action_type}' not in whitelist")
        if p.action_type == CREATE_SKILL_ACTION:
            if p.target_file in current_skills:
                errors.append(f"[{p.target_file}] create_skill target already exists")
            if p.target_file not in proposed_files:
                errors.append(f"[{p.target_file}] create_skill target missing from output")
            if (err := _validate_create_target(p.target_file, role)):
                errors.append(f"[{p.target_file}] {err}")
            continue
        if p.target_file not in current_skills:
            errors.append(f"[{p.target_file}] target does not exist; use {CREATE_SKILL_ACTION}")
            continue
        old_fm, _ = parse_front_matter(current_skills.get(p.target_file, ""))
        evo = old_fm.get("evolution", {})
        if isinstance(evo, dict) and evo.get("enabled"):
            allowed = set(evo.get("allowed_actions", []))
            if allowed and p.action_type not in allowed:
                errors.append(
                    f"[{p.target_file}] action_type '{p.action_type}' not in allowed_actions {allowed}"
                )

    # 2. No deletion — every current file must survive.
    for fname in current_skills:
        if fname not in proposed_files:
            errors.append(f"File '{fname}' would be deleted (missing from output)")

    # Per-file structural checks.
    for fname, new_content in proposed_files.items():
        old_content = current_skills.get(fname)
        is_new = old_content is None
        if is_new:
            if fname not in create_targets:
                errors.append(f"[{fname}] new file requires action_type '{CREATE_SKILL_ACTION}'")
            if (err := _validate_create_file(fname, new_content, role, valid_roles, AGENT_ACTION_TYPES)):
                errors.append(f"[{fname}] {err}")
        else:
            errors.extend(f"[{fname}] {e}" for e in _validate_existing(new_content, old_content, eligible, fname))
        if _validate_front_matter(new_content) is None:
            errors.append(f"[{fname}] YAML front matter is not parseable")
        if len(new_content) > MAX_SKILL_LENGTH:
            errors.append(f"[{fname}] length {len(new_content)} exceeds {MAX_SKILL_LENGTH}")

    # Aggregate caps.
    if _count_role_skills(proposed_files, role) > MAX_ACTIVE_SKILLS_PER_ROLE:
        errors.append(f"Role '{role}' would exceed {MAX_ACTIVE_SKILLS_PER_ROLE} active skills")
    if sum(len(v) for v in proposed_files.values()) > MAX_CHANGED_FILES * MAX_SKILL_LENGTH:
        errors.append("Total output size exceeds limit")
    return errors


def _validate_front_matter(content: str) -> dict | None:
    from app.services.prompt import parse_front_matter

    try:
        fm, _ = parse_front_matter(content)
        return fm or None
    except Exception:
        return None


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []


def _validate_create_target(path: str, role: str) -> str | None:
    from storage.interfaces import normalize_skill_path

    try:
        normalized = normalize_skill_path(path)
    except ValueError as exc:
        return str(exc)
    if normalized != path.replace("\\", "/"):
        return f"target_file must already be normalized, got '{path}'"
    p = PurePosixPath(normalized)
    if len(p.parts) != 1:
        return f"create_skill target must be '<slug>.md' inside the '{role}' version"
    if not _CREATE_SKILL_SLUG_RE.match(p.stem):
        return "create_skill slug must be 2-49 chars of [a-z0-9_-]"
    return None


def _validate_create_file(
    path: str, content: str, role: str, valid_roles: set[str], valid_actions: frozenset[str]
) -> str | None:
    if (err := _validate_create_target(path, role)):
        return err
    fm = _validate_front_matter(content)
    if fm is None:
        return "YAML front matter is not parseable"
    if str(fm.get("role", "")) != role:
        return f"role must be '{role}', got '{fm.get('role', '')}'"
    if role not in valid_roles:
        return f"unknown role '{role}'"
    if not str(fm.get("name", "")).strip():
        return "name is required"
    actions = set(_as_str_list(fm.get("applicable_actions", [])))
    if not actions:
        return "applicable_actions must contain at least one game action"
    if (invalid := sorted(actions - valid_actions)):
        return f"unknown applicable_actions: {invalid}"
    evo = fm.get("evolution", {})
    if not isinstance(evo, dict) or not bool(evo.get("enabled", False)):
        return "created skills must set evolution.enabled=true"
    allowed = set(_as_str_list(evo.get("allowed_actions", [])))
    if not allowed:
        return "created skills must declare evolution.allowed_actions"
    if (invalid := sorted(allowed - GLOBAL_ALLOWED_MODIFY_ACTIONS)):
        return f"invalid evolution.allowed_actions: {invalid}"
    return None


def _validate_existing(
    new_content: str, old_content: str, eligible: list[SkillProposal], fname: str
) -> list[str]:
    from app.services.prompt import parse_front_matter

    issues: list[str] = []
    new_fm, _ = parse_front_matter(new_content)
    old_fm, _ = parse_front_matter(old_content)
    if old_fm.get("name") and new_fm.get("name") != old_fm.get("name"):
        issues.append("name changed")
    if old_fm.get("role") and new_fm.get("role") != old_fm.get("role"):
        issues.append("role changed")
    old_actions = set(_as_str_list(old_fm.get("applicable_actions", [])))
    new_actions = set(_as_str_list(new_fm.get("applicable_actions", [])))
    if old_actions and old_actions != new_actions:
        issues.append("applicable_actions changed")
    old_evo = json.dumps(old_fm.get("evolution", {}), sort_keys=True)
    new_evo = json.dumps(new_fm.get("evolution", {}), sort_keys=True)
    if old_evo != new_evo:
        issues.append("evolution field must not be modified by applier")
    if (err := _validate_slow_update(old_content, new_content)):
        issues.append(err)
    return issues


def _validate_slow_update(old_content: str, new_content: str) -> str | None:
    old_regions = _SLOW_UPDATE_PATTERN.findall(old_content)
    if not old_regions:
        return None
    new_regions = _SLOW_UPDATE_PATTERN.findall(new_content)
    if not new_regions:
        return "slow_update region was deleted"
    for i, old_region in enumerate(old_regions):
        if i >= len(new_regions):
            return f"slow_update region {i + 1} was deleted"
        if old_region.strip() not in new_regions[i].strip():
            return f"slow_update region {i + 1} content was modified"
    return None


def _count_role_skills(files: dict[str, str], role: str) -> int:
    from app.services.prompt import parse_front_matter

    count = 0
    for fname, content in files.items():
        if PurePosixPath(fname.replace("\\", "/")).suffix != ".md":
            continue
        try:
            fm, _ = parse_front_matter(content)
        except Exception:
            continue
        if str(fm.get("role", "")) == role:
            count += 1
    return count


def _smoke_test(proposed_files: dict[str, str]) -> tuple[bool, str]:
    """Write files to a temp dir and verify they load via load_markdown_skills."""
    import tempfile

    from app.services.prompt import load_markdown_skill_report

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for fname, content in proposed_files.items():
                fpath = root / fname
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(content, encoding="utf-8")
            report = load_markdown_skill_report(root)
            details = "; ".join(d.format() for d in report.diagnostics)
            if not report.skills:
                suffix = f": {details}" if details else ""
                return False, f"load_markdown_skills returned empty list{suffix}"
            if len(report.skills) < len(proposed_files):
                suffix = f": {details}" if details else ""
                return False, f"expected {len(proposed_files)} skills, loaded {len(report.skills)}{suffix}"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _build_diffs(
    current_skills: dict[str, str],
    proposed_files: dict[str, str],
    changes: list[dict[str, str]],
    eligible: list[SkillProposal],
) -> list[SkillDiff]:
    target_to_proposal = {p.target_file: p.proposal_id for p in eligible}
    diffs: list[SkillDiff] = []
    for fname, new_content in proposed_files.items():
        old_content = current_skills.get(fname)
        if old_content == new_content:
            continue
        diffs.append(SkillDiff(
            filename=fname,
            action="modified" if old_content is not None else "created",
            proposal_ref=target_to_proposal.get(fname, ""),
            before=old_content,
            after=new_content,
        ))
    return diffs
