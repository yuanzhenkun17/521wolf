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

from app.config import DEFAULT_GAME_CONCURRENCY
from app.util.json import compact_json, to_jsonable

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class EvolutionStatus(str, Enum):
    QUEUED = "queued"
    TRAINING = "training"
    CONSOLIDATING = "consolidating"
    APPLYING = "applying"
    SCENARIO_REPLAY = "scenario_replay"
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
    title: str = ""
    section: str = ""
    content: str = ""
    rationale: str = ""
    hypothesis: str = ""
    problem_observation: str = ""
    trigger_condition: dict[str, Any] = field(default_factory=dict)
    expected_effect: dict[str, Any] = field(default_factory=dict)
    metric_targets: dict[str, Any] = field(default_factory=dict)
    evidence_game_ids: list[str] = field(default_factory=list)
    counter_evidence_game_ids: list[str] = field(default_factory=list)
    diff_intent: str = ""
    confidence: float = 0.0
    risk: str = "medium"
    risk_tags: list[str] = field(default_factory=list)
    failure_mode: str = ""
    expected_metric: str = ""
    expected_direction: str = "improve"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    status: str = "proposed"
    quality_score: dict[str, Any] = field(default_factory=dict)
    preflight_status: str = "pending"
    preflight_reasons: list[str] = field(default_factory=list)
    preflight_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "target_file": self.target_file,
            "action_type": self.action_type,
            "title": self.title,
            "section": self.section,
            "content": self.content,
            "rationale": self.rationale,
            "hypothesis": self.hypothesis,
            "problem_observation": self.problem_observation,
            "trigger_condition": dict(self.trigger_condition),
            "expected_effect": dict(self.expected_effect),
            "metric_targets": dict(self.metric_targets),
            "evidence_game_ids": list(self.evidence_game_ids),
            "counter_evidence_game_ids": list(self.counter_evidence_game_ids),
            "diff_intent": self.diff_intent,
            "confidence": self.confidence,
            "risk": self.risk,
            "risk_tags": list(self.risk_tags),
            "failure_mode": self.failure_mode,
            "expected_metric": self.expected_metric,
            "expected_direction": self.expected_direction,
            "evidence": self.evidence,
            "conflicts_with": self.conflicts_with,
            "status": self.status,
            "quality_score": dict(self.quality_score),
            "preflight_status": self.preflight_status,
            "preflight_reasons": list(self.preflight_reasons),
            "preflight_report": dict(self.preflight_report),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillProposal:
        if data is None:
            return cls()
        return cls(
            proposal_id=str(data.get("proposal_id", "")),
            target_file=str(data.get("target_file", "")),
            action_type=str(data.get("action_type", "")),
            title=str(data.get("title", "")),
            section=str(data.get("section", "")),
            content=str(data.get("content", "")),
            rationale=str(data.get("rationale", "")),
            hypothesis=str(data.get("hypothesis", "")),
            problem_observation=str(data.get("problem_observation", "")),
            trigger_condition=dict(data.get("trigger_condition", {}) or {}) if isinstance(data.get("trigger_condition", {}), dict) else {},
            expected_effect=dict(data.get("expected_effect", {}) or {}) if isinstance(data.get("expected_effect", {}), dict) else {},
            metric_targets=dict(data.get("metric_targets", {}) or {}) if isinstance(data.get("metric_targets", {}), dict) else {},
            evidence_game_ids=[str(g) for g in data.get("evidence_game_ids", [])],
            counter_evidence_game_ids=[str(g) for g in data.get("counter_evidence_game_ids", [])],
            diff_intent=str(data.get("diff_intent", "")),
            confidence=float(data.get("confidence", 0.0)),
            risk=str(data.get("risk", data.get("risk_level", "medium"))),
            risk_tags=[str(tag) for tag in data.get("risk_tags", [])],
            failure_mode=str(data.get("failure_mode", "")),
            expected_metric=str(data.get("expected_metric", "")),
            expected_direction=str(data.get("expected_direction", "improve")),
            evidence=[dict(e) for e in data.get("evidence", [])],
            conflicts_with=[str(c) for c in data.get("conflicts_with", [])],
            status=str(data.get("status", "proposed")),
            quality_score=dict(data.get("quality_score", {}) or {}),
            preflight_status=str(data.get("preflight_status", "pending")),
            preflight_reasons=[str(r) for r in data.get("preflight_reasons", [])],
            preflight_report=dict(data.get("preflight_report", {}) or {}),
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
    generated_proposal_ids: list[str] = field(default_factory=list)
    preflight_passed_proposal_ids: list[str] = field(default_factory=list)
    preflight_rejected_proposal_ids: list[str] = field(default_factory=list)
    accepted_proposal_ids: list[str] = field(default_factory=list)
    rejected_proposal_ids: list[str] = field(default_factory=list)
    preflight_reports: list[dict[str, Any]] = field(default_factory=list)
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
            "generated_proposal_ids": list(self.generated_proposal_ids),
            "preflight_passed_proposal_ids": list(self.preflight_passed_proposal_ids),
            "preflight_rejected_proposal_ids": list(self.preflight_rejected_proposal_ids),
            "accepted_proposal_ids": list(self.accepted_proposal_ids),
            "rejected_proposal_ids": list(self.rejected_proposal_ids),
            "preflight_reports": [dict(item) for item in self.preflight_reports],
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
            generated_proposal_ids=[str(p) for p in data.get("generated_proposal_ids", [])],
            preflight_passed_proposal_ids=[str(p) for p in data.get("preflight_passed_proposal_ids", [])],
            preflight_rejected_proposal_ids=[str(p) for p in data.get("preflight_rejected_proposal_ids", [])],
            accepted_proposal_ids=[str(p) for p in data.get("accepted_proposal_ids", [])],
            rejected_proposal_ids=[str(p) for p in data.get("rejected_proposal_ids", [])],
            preflight_reports=[dict(item) for item in data.get("preflight_reports", []) if isinstance(item, dict)],
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
    for game_id in _as_str_list(data.get("evidence_game_ids")):
        if game_id:
            game_ids.add(game_id)
    risk = str(data.get("risk", data.get("risk_level", "medium"))).lower()
    duplicate_rejected = _proposal_matches_rejected(data, rejected or [])
    high_risk_fields = _proposal_high_risk_fields(data)
    evidence_count = len(evidence)
    covered_game_count = len(game_ids)
    has_hypothesis = bool(str(data.get("hypothesis", "")).strip())
    has_trigger = bool(_non_empty_mapping(data.get("trigger_condition")))
    has_metric_target = bool(_non_empty_mapping(data.get("metric_targets")))

    score = 0.0
    score += min(evidence_count, 4) * 0.12
    score += min(covered_game_count, 4) * 0.12
    score += max(0.0, min(1.0, _as_float(data.get("confidence"), 0.0))) * 0.24
    score += {"low": 0.16, "medium": 0.08, "high": -0.20}.get(risk, 0.0)
    if has_hypothesis:
        score += 0.08
    if has_trigger:
        score += 0.08
    if has_metric_target:
        score += 0.08
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
        "has_hypothesis": has_hypothesis,
        "has_trigger_condition": has_trigger,
        "has_metric_targets": has_metric_target,
    }


def annotate_proposal_quality(
    proposals: list[SkillProposal],
    *,
    rejected: list[dict[str, Any]] | None = None,
) -> None:
    """Attach deterministic quality_score to proposals in place."""
    for proposal in proposals:
        proposal.quality_score = score_proposal_quality(proposal, rejected=rejected)


def preflight_proposal(
    proposal: SkillProposal | dict[str, Any],
    raw: dict[str, Any] | None = None,
    *,
    rejected: list[dict[str, Any]] | None = None,
    duplicate_threshold: float = 0.72,
) -> dict[str, Any]:
    """Run deterministic Phase-A proposal checks before candidate build."""
    row = proposal.to_dict() if isinstance(proposal, SkillProposal) else dict(proposal or {})
    raw_data = dict(raw or row)
    evidence_rows = [dict(item) for item in row.get("evidence", []) if isinstance(item, dict)]
    evidence_game_ids = sorted(_proposal_source_game_ids(raw_data, evidence_rows))
    for game_id in _as_str_list(row.get("evidence_game_ids")):
        if game_id and game_id not in evidence_game_ids:
            evidence_game_ids.append(game_id)

    reasons: list[str] = []
    checks: dict[str, Any] = {
        "has_hypothesis": bool(str(row.get("hypothesis", "")).strip()),
        "has_trigger_condition": _non_empty_mapping(row.get("trigger_condition")),
        "has_expected_effect": _non_empty_mapping(row.get("expected_effect")),
        "has_metric_targets": _non_empty_mapping(row.get("metric_targets")),
        "evidence_game_count": len(evidence_game_ids),
        "risk": str(row.get("risk", row.get("risk_level", "medium"))).lower(),
    }

    for field_name in ("target_file", "action_type", "content", "rationale"):
        if not str(row.get(field_name, "")).strip():
            reasons.append(f"missing {field_name}")
    if not checks["has_hypothesis"]:
        reasons.append("missing hypothesis")
    if not checks["has_trigger_condition"]:
        reasons.append("missing trigger_condition")
    if not checks["has_expected_effect"]:
        reasons.append("missing expected_effect")
    if not checks["has_metric_targets"]:
        reasons.append("missing metric_targets")
    if checks["evidence_game_count"] < 2:
        reasons.append("requires evidence from at least 2 distinct game_id values")
    if checks["risk"] == "high":
        reasons.append("high risk proposals require manual review")

    high_risk_fields = _proposal_high_risk_fields(row)
    if high_risk_fields:
        reasons.append("touches high-risk fields: " + ",".join(high_risk_fields))
    checks["high_risk_fields"] = high_risk_fields

    policy_specific_tags = _proposal_policy_specific_tags(row)
    if policy_specific_tags:
        reasons.append("strategy condition is overfit-specific: " + ",".join(policy_specific_tags))
    checks["policy_specific_tags"] = policy_specific_tags

    similarity = reject_buffer_similarity(row, rejected, threshold=duplicate_threshold)
    checks["reject_buffer_similarity"] = similarity
    if similarity["duplicate_rejected"]:
        reasons.append("duplicate rejected proposal direction")

    status = "blocked" if reasons else "passed"
    report = {
        "proposal_id": str(row.get("proposal_id", "")),
        "status": status,
        "reasons": _unique_str(reasons),
        "evidence_game_ids": evidence_game_ids,
        "checks": checks,
    }
    if isinstance(proposal, SkillProposal):
        proposal.preflight_status = status
        proposal.preflight_reasons = list(report["reasons"])
        proposal.preflight_report = dict(report)
        proposal.evidence_game_ids = list(evidence_game_ids)
    return report


# ---------------------------------------------------------------------------
# Trust loop helpers: review state, paired battles, gate reports, reject risk
# ---------------------------------------------------------------------------

PROPOSAL_REVIEW_STATUSES = {"proposed", "accepted", "rejected"}
_ACCEPTED_STATUS_ALIASES = {
    "accept",
    "accepted",
    "approve",
    "approved",
    "apply",
    "applied",
    "promote",
    "promoted",
    "yes",
    "true",
}
_REJECTED_STATUS_ALIASES = {
    "reject",
    "rejected",
    "decline",
    "declined",
    "deny",
    "denied",
    "drop",
    "dropped",
    "block",
    "blocked",
    "no",
    "false",
}
_PROPOSED_STATUS_ALIASES = {
    "",
    "new",
    "open",
    "pending",
    "proposal",
    "proposed",
    "review",
    "reviewing",
    "queued",
    "skipped",
}


def normalize_proposal_review_status(value: Any, *, default: str = "proposed") -> str:
    """Return canonical proposal review status: proposed, accepted, or rejected."""
    fallback = default if default in PROPOSAL_REVIEW_STATUSES else "proposed"
    if value is None:
        return fallback
    if isinstance(value, bool):
        return "accepted" if value else "rejected"
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if text in _ACCEPTED_STATUS_ALIASES:
        return "accepted"
    if text in _REJECTED_STATUS_ALIASES:
        return "rejected"
    if text in _PROPOSED_STATUS_ALIASES:
        return "proposed"
    return fallback


def normalize_proposal_reviews(
    proposals: list[SkillProposal | dict[str, Any]],
    decisions: dict[str, Any] | list[dict[str, Any]] | None = None,
    *,
    default: str = "proposed",
) -> list[dict[str, Any]]:
    """Return proposal dicts with canonical review/status fields.

    ``decisions`` may be a mapping of proposal_id -> status/decision row, or a
    list of rows containing proposal_id plus status/review_status/decision.
    The input proposals are not mutated.
    """
    decision_by_id = _proposal_decision_map(decisions)
    normalized: list[dict[str, Any]] = []
    for proposal in proposals or []:
        row = proposal.to_dict() if isinstance(proposal, SkillProposal) else dict(proposal)
        proposal_id = str(row.get("proposal_id", ""))
        decision = decision_by_id.get(proposal_id, {})
        row_status = _first_present(row, ("review_status", "status", "decision"), default_value=default)
        if isinstance(decision, dict):
            status_value = _first_present(
                decision,
                ("review_status", "status", "decision", "action"),
                default_value=row_status,
            )
        elif proposal_id in decision_by_id:
            status_value = decision
        else:
            status_value = row_status
        status = normalize_proposal_review_status(status_value, default=default)
        row["status"] = status
        row["review_status"] = status
        if isinstance(decision, dict):
            for key in ("review_reason", "reviewed_by", "reviewed_at", "risk_tags"):
                if key in decision:
                    row[key] = decision[key]
        normalized.append(row)
    return normalized


def accepted_proposals_for_apply(
    proposals: list[SkillProposal | dict[str, Any]],
    decisions: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return accepted proposals converted to legacy ``status=proposed``.

    The applier currently treats ``status=proposed`` as eligible. This adapter
    lets a future review endpoint apply only accepted rows without changing the
    legacy applier contract.
    """
    accepted: list[dict[str, Any]] = []
    for row in normalize_proposal_reviews(proposals, decisions):
        if row.get("review_status") != "accepted":
            continue
        item = dict(row)
        item["status"] = "proposed"
        accepted.append(item)
    return accepted


def build_paired_seed_battle_table(
    run: dict[str, Any] | None = None,
    *,
    battle_result: dict[str, Any] | None = None,
    role: str = "",
    target_team: str = "",
) -> list[dict[str, Any]]:
    """Build paired baseline/candidate rows keyed by seed.

    Accepts either a persisted run shape containing ``battle_games`` or a
    battle_result containing side game lists. Missing sides are preserved as
    unrankable rows so callers can explain sample loss.
    """
    result = battle_result if isinstance(battle_result, dict) else {}
    run_data = run if isinstance(run, dict) else {}
    if not result and isinstance(run_data.get("battle_result"), dict):
        result = dict(run_data.get("battle_result") or {})
    resolved_role = role or str(run_data.get("role") or "")
    target = target_team or str(result.get("target_team") or "")
    games = _collect_battle_games(run_data, result)
    by_seed: dict[Any, dict[str, Any]] = {}
    for game in games:
        if not isinstance(game, dict):
            continue
        seed = game.get("seed")
        if seed is None:
            seed = _infer_seed_from_game_id(game.get("game_id") or game.get("source_game_id"))
        if seed is None:
            seed = game.get("game_id") or game.get("source_game_id") or len(by_seed)
        side = _battle_game_side(game)
        if side not in {"baseline", "candidate"}:
            continue
        row = by_seed.setdefault(seed, {"seed": seed})
        row[side] = dict(game)

    seeds = list(result.get("seeds") or [])
    for seed in seeds:
        by_seed.setdefault(seed, {"seed": seed})

    rows = [_build_paired_seed_row(seed, pair, role=resolved_role, target_team=target) for seed, pair in by_seed.items()]
    return sorted(rows, key=lambda item: str(item.get("seed", "")))


def build_evolution_gate_report(
    run: dict[str, Any] | None = None,
    *,
    battle_result: dict[str, Any] | None = None,
    proposals: list[SkillProposal | dict[str, Any]] | None = None,
    rejected: list[dict[str, Any]] | None = None,
    role: str = "",
    target_team: str = "",
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a machine-readable promotion gate report for the trust loop."""
    run_data = run if isinstance(run, dict) else {}
    result = battle_result if isinstance(battle_result, dict) else {}
    if not result and isinstance(run_data.get("battle_result"), dict):
        result = dict(run_data.get("battle_result") or {})
    resolved_role = role or str(run_data.get("role") or "")
    target = target_team or str(result.get("target_team") or "")
    threshold_values = _gate_thresholds(thresholds)
    paired_rows = build_paired_seed_battle_table(
        run_data,
        battle_result=result,
        role=resolved_role,
        target_team=target,
    )
    paired_summary = _paired_seed_summary(paired_rows)
    role_score = _role_score_gate_summary(paired_rows, result)
    decision_quality = _decision_quality_summary_for_gate(paired_rows, run_data, result)
    scenario_replay = _scenario_replay_gate_summary(run_data, result)
    proposal_rows = normalize_proposal_reviews(_proposal_rows(proposals, run_data), default="proposed")
    policy_versions = _gate_policy_versions(run_data, result, role=resolved_role)
    proposal_risks = [
        assess_proposal_risk(
            proposal,
            rejected=rejected,
            paired_seed_table=paired_rows,
            duplicate_threshold=float(threshold_values["duplicate_similarity_threshold"]),
        )
        for proposal in proposal_rows
    ]
    risk_tags = sorted({tag for risk in proposal_risks for tag in risk.get("risk_tags", [])})
    proposal_attribution = build_proposal_attribution_report(
        run_data,
        battle_result=result,
        proposals=proposal_rows,
        proposal_risks=proposal_risks,
        paired_seed_table=paired_rows,
    )

    blocked_reasons: list[str] = []
    review_reasons: list[str] = []
    battle_passed = bool(result.get("significant"))
    if result.get("skipped"):
        blocked_reasons.append(str(result.get("reason") or "battle_skipped"))
    elif not battle_passed:
        blocked_reasons.append("battle_not_significant")
    if paired_summary["valid_count"] < threshold_values["min_paired_valid_seeds"]:
        review_reasons.append("paired_valid_count_below_minimum")
    if role_score["delta"] is not None and role_score["delta"] < threshold_values["min_role_score_delta"]:
        review_reasons.append("role_score_delta_below_minimum")
    if decision_quality["candidate"]["issue_rate"] > threshold_values["max_decision_issue_rate"]:
        review_reasons.append("candidate_decision_issue_rate_above_ceiling")
    if decision_quality["delta"] > threshold_values["max_decision_issue_delta"]:
        review_reasons.append("decision_issue_delta_above_ceiling")
    if paired_summary["valid_count"] and paired_summary["candidate_edge_rate"] < threshold_values["min_candidate_edge_rate"]:
        review_reasons.append("paired_candidate_edge_rate_below_minimum")
    if "duplicate_rejected" in risk_tags:
        review_reasons.append("proposal_duplicates_rejected_buffer")
    if "overfit_high" in risk_tags:
        review_reasons.append("proposal_overfit_risk_high")
    if any(str(row.get("risk", "")).lower() == "high" for row in proposal_rows):
        review_reasons.append("proposal_high_risk")
    if proposal_attribution.get("review_required"):
        review_reasons.append("proposal_attribution_inconclusive")
    if scenario_replay["execution_mode"] != "contract_only":
        if scenario_replay["policy_violation_count"] > 0:
            blocked_reasons.append("scenario_policy_violation")
        if scenario_replay["verdict"] in {"candidate_worse", "review_required"}:
            review_reasons.append("scenario_replay_not_passed")

    blocked_reasons = _unique_str(blocked_reasons)
    review_reasons = _unique_str(review_reasons)
    trust_bundle_completeness = _trust_bundle_completeness(
        run_data,
        result,
        proposal_rows=proposal_rows,
        paired_rows=paired_rows,
        scenario_replay=scenario_replay,
        policy_versions=policy_versions,
    )
    promote_allowed = battle_passed and not blocked_reasons and not review_reasons
    if promote_allowed:
        decision = "promote"
    elif blocked_reasons and "battle_not_significant" in blocked_reasons:
        decision = "reject"
    else:
        decision = "review_required"
    release_gate = _release_gate_v2(
        battle_passed=battle_passed,
        blocked_reasons=blocked_reasons,
        review_reasons=review_reasons,
        paired_summary=paired_summary,
        role_score=role_score,
        decision_quality=decision_quality,
        scenario_replay=scenario_replay,
        proposal_rows=proposal_rows,
        risk_tags=risk_tags,
        thresholds=threshold_values,
        trust_bundle_completeness=trust_bundle_completeness,
    )

    return {
        "schema_version": "trust_loop_gate_v1",
        "decision": decision,
        "promote_allowed": promote_allowed,
        "gate_policy_version": policy_versions["gate_policy_version"],
        "score_policy_version": policy_versions["score_policy_version"],
        "judge_policy_version": policy_versions["judge_policy_version"],
        "rubric_version": policy_versions["rubric_version"],
        "policy_versions": policy_versions,
        "release_gate": release_gate,
        "release_decision": release_gate["decision"],
        "blocked_reasons": blocked_reasons,
        "review_reasons": review_reasons,
        "reasons": _unique_str([*blocked_reasons, *review_reasons]),
        "thresholds": threshold_values,
        "metrics": {
            "win_rate_delta": _as_float(result.get("win_rate_delta"), 0.0),
            "role_score_delta": role_score["delta"],
            "paired_valid_count": paired_summary["valid_count"],
            "paired_candidate_wins": paired_summary["candidate_wins"],
            "paired_baseline_wins": paired_summary["baseline_wins"],
            "paired_ties": paired_summary["ties"],
            "paired_candidate_edge_rate": paired_summary["candidate_edge_rate"],
            "decision_issue_delta": decision_quality["delta"],
            "scenario_count": scenario_replay["scenario_count"],
            "scenario_policy_violation_count": scenario_replay["policy_violation_count"],
        },
        "role_score": role_score,
        "scenario_replay": scenario_replay,
        "paired_seed_summary": paired_rows,
        "paired_summary": paired_summary,
        "decision_quality": decision_quality,
        "trust_bundle_completeness": trust_bundle_completeness,
        "proposal_attribution": proposal_attribution,
        "risk_tags": risk_tags,
        "proposal_risks": proposal_risks,
        "significance": {
            "passed": battle_passed,
            "reasons": list((result.get("significance") or {}).get("reasons", []) or [])
            if isinstance(result.get("significance"), dict) else [],
        },
    }


def build_trust_bundle(
    run: dict[str, Any] | None = None,
    *,
    battle_result: dict[str, Any] | None = None,
    gate_report: dict[str, Any] | None = None,
    proposals: list[SkillProposal | dict[str, Any]] | None = None,
    diff: list[SkillDiff | dict[str, Any]] | None = None,
    review_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the auditable trust bundle for one evolution run.

    The bundle is a manifest over already-persisted run artifacts. It does not
    claim a dedicated replay CLI exists unless the run explicitly provides one.
    """
    run_data = run if isinstance(run, dict) else {}
    result = battle_result if isinstance(battle_result, dict) else {}
    if not result and isinstance(run_data.get("battle_result"), dict):
        result = dict(run_data.get("battle_result") or {})
    report = gate_report if isinstance(gate_report, dict) else {}
    if not report:
        candidate_report = result.get("gate_report")
        if isinstance(candidate_report, dict):
            report = dict(candidate_report)
        elif isinstance(run_data.get("gate_report"), dict):
            report = dict(run_data.get("gate_report") or {})
    proposal_rows = normalize_proposal_reviews(_proposal_rows(proposals, run_data), default="proposed")
    diff_rows = _trust_bundle_diff_rows(diff if diff is not None else run_data.get("diff"))
    paired_rows = build_paired_seed_battle_table(
        run_data,
        battle_result=result,
        role=str(run_data.get("role") or ""),
        target_team=str(result.get("target_team") or ""),
    )
    scenario_snapshots = [dict(item) for item in run_data.get("scenario_snapshots", []) or [] if isinstance(item, dict)]
    if not scenario_snapshots and isinstance(result.get("scenario_replay_report"), dict):
        scenario_snapshots = [
            {"scenario_id": row.get("scenario_id"), "source_game_id": row.get("source_game_id")}
            for row in result.get("scenario_replay_report", {}).get("results", []) or []
            if isinstance(row, dict)
        ]
    policy_versions = _gate_policy_versions(run_data, result, role=str(run_data.get("role") or ""))
    if isinstance(report.get("policy_versions"), dict):
        policy_versions.update({key: str(value) for key, value in report["policy_versions"].items() if value})
    thresholds = report.get("thresholds") if isinstance(report.get("thresholds"), dict) else {}
    run_id = str(run_data.get("run_id") or "")
    baseline_version = run_data.get("parent_hash") or result.get("baseline_version")
    candidate_version = run_data.get("candidate_hash") or result.get("candidate_version")
    generated_ids = _trust_bundle_ids(
        run_data.get("generated_proposal_ids"),
        fallback=[row.get("proposal_id") for row in proposal_rows],
    )
    preflight_passed_ids = _trust_bundle_ids(run_data.get("preflight_passed_proposal_ids"))
    accepted_ids = _trust_bundle_ids(run_data.get("accepted_proposal_ids"))
    rejected_ids = _trust_bundle_ids(run_data.get("rejected_proposal_ids"))
    if not accepted_ids:
        accepted_ids = [str(row.get("proposal_id")) for row in proposal_rows if row.get("review_status") == "accepted" and row.get("proposal_id")]
    if not rejected_ids:
        rejected_ids = [str(row.get("proposal_id")) for row in proposal_rows if row.get("review_status") == "rejected" and row.get("proposal_id")]
    events = [dict(item) for item in review_events or [] if isinstance(item, dict)]
    if not events:
        events = _proposal_review_events(proposal_rows)
    bundle = {
        "schema_version": "trust_bundle_v1",
        "run_id": run_id,
        "role": str(run_data.get("role") or ""),
        "baseline_version": baseline_version,
        "candidate_version": candidate_version,
        "training_game_ids": _game_ids(run_data.get("training_games")),
        "scenario_ids": _scenario_ids(scenario_snapshots),
        "battle_pair_seeds": [row.get("seed") for row in paired_rows],
        "proposal_ids": [str(row.get("proposal_id")) for row in proposal_rows if row.get("proposal_id")],
        "generated_proposal_ids": generated_ids,
        "preflight_passed_proposal_ids": preflight_passed_ids,
        "accepted_proposal_ids": accepted_ids,
        "rejected_proposal_ids": rejected_ids,
        "diff_hash": _sha256_json(diff_rows),
        "gate_report_id": _gate_report_id(run_id, report),
        "attribution_report_id": _attribution_report_id(run_id, report.get("proposal_attribution")),
        "gate_policy_version": policy_versions["gate_policy_version"],
        "score_policy_version": policy_versions["score_policy_version"],
        "judge_policy_version": policy_versions["judge_policy_version"],
        "rubric_version": policy_versions["rubric_version"],
        "thresholds": dict(thresholds),
        "review_events": events,
        "shadow_version_id": run_data.get("shadow_version_id"),
        "canary_version_id": run_data.get("canary_version_id"),
        "published_version_id": run_data.get("published_version_id") or result.get("published_version_id"),
        "rollback_target": baseline_version,
        "repro_command": _repro_command(run_data),
    }
    bundle_hash = _sha256_json(bundle)
    bundle["bundle_hash"] = bundle_hash
    bundle["trust_bundle_id"] = _trust_bundle_id(run_id, bundle_hash)
    bundle["completeness"] = _trust_bundle_manifest_completeness(bundle)
    return bundle


def build_proposal_attribution_report(
    run: dict[str, Any] | None = None,
    *,
    battle_result: dict[str, Any] | None = None,
    proposals: list[SkillProposal | dict[str, Any]] | None = None,
    proposal_risks: list[dict[str, Any]] | None = None,
    paired_seed_table: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a conservative attribution report without inventing ablation data.

    Until scenario/full-game ablation is wired, package-level A/B cannot prove
    individual proposal contribution. The report records the budget and the
    proposal rows that should be ablated later, then marks attribution as
    inconclusive instead of assigning fake contribution scores.
    """
    run_data = run if isinstance(run, dict) else {}
    result = battle_result if isinstance(battle_result, dict) else {}
    if not result and isinstance(run_data.get("battle_result"), dict):
        result = dict(run_data.get("battle_result") or {})
    existing = run_data.get("proposal_attribution_report") or result.get("proposal_attribution_report")
    if isinstance(existing, dict) and existing.get("schema_version"):
        return dict(existing)

    proposal_rows = normalize_proposal_reviews(_proposal_rows(proposals, run_data), default="proposed")
    budget = _proposal_attribution_budget(run_data)
    paired_summary = _paired_seed_summary(paired_seed_table or [])
    risks_by_id = {
        str(item.get("proposal_id") or ""): dict(item)
        for item in proposal_risks or []
        if isinstance(item, dict)
    }
    rows = [
        _proposal_attribution_row(row, risks_by_id.get(str(row.get("proposal_id") or ""), {}), budget=budget)
        for row in proposal_rows
    ]
    required_rows = [row for row in rows if row.get("requires_ablation")]
    if not proposal_rows:
        status = "skipped"
        reason = "no_proposals"
    else:
        status = "attribution_inconclusive"
        reason = "ablation_not_run"
    review_required = bool(
        status == "attribution_inconclusive"
        and (
            len(proposal_rows) > 1
            or required_rows
            or paired_summary.get("valid_count", 0) < int(budget.get("min_paired_valid_seeds_for_attribution", 0) or 0)
        )
    )
    return {
        "schema_version": "proposal_attribution_report_v1",
        "status": status,
        "reason": reason,
        "review_required": review_required,
        "package_proposal_count": len(proposal_rows),
        "attribution_confidence": "none" if status == "attribution_inconclusive" else "not_applicable",
        "budget": budget,
        "paired_summary": paired_summary,
        "rows": rows,
        "ablation_candidate_proposal_ids": [row["proposal_id"] for row in required_rows if row.get("proposal_id")],
    }


def reject_buffer_similarity(
    proposal: SkillProposal | dict[str, Any],
    rejected: list[dict[str, Any]] | None,
    *,
    threshold: float = 0.72,
) -> dict[str, Any]:
    """Compare one proposal with rejected-buffer entries."""
    row = proposal.to_dict() if isinstance(proposal, SkillProposal) else dict(proposal or {})
    best: dict[str, Any] | None = None
    best_score = 0.0
    for item in rejected or []:
        if not isinstance(item, dict):
            continue
        score = _proposal_similarity(row, item)
        if score > best_score:
            best_score = score
            best = item
    duplicate = bool(best is not None and best_score >= threshold)
    return {
        "duplicate_rejected": duplicate,
        "similarity": round(best_score, 4),
        "threshold": threshold,
        "matched_rejection": _compact_rejection_match(best) if duplicate else None,
        "normalized_hash": _normalized_proposal_hash(row),
    }


def detect_overfit_risk(
    proposal: SkillProposal | dict[str, Any],
    *,
    paired_seed_table: list[dict[str, Any]] | None = None,
    rejected: list[dict[str, Any]] | None = None,
    duplicate_threshold: float = 0.72,
) -> dict[str, Any]:
    """Return deterministic overfit risk tags and gate effect for a proposal."""
    row = proposal.to_dict() if isinstance(proposal, SkillProposal) else dict(proposal or {})
    text = _proposal_risk_text(row).lower()
    tags: list[str] = []
    evidence: list[str] = []

    pattern_checks = [
        ("seed_specific", r"\bseed[_\s:#-]*\d+\b"),
        ("game_id_specific", r"\b(game_id|source_game_id)\b|\b[a-z]+_[a-z0-9_]*_\d{3,}\b"),
        ("player_specific", r"\b(player|p)[_\s:#-]*\d+\b|\d+\s*号"),
        ("model_specific", r"\b(model_id|gpt-|claude|deepseek|qwen|glm)\b"),
        ("database_specific", r"\b(postgres|postgresql|database|run_id|table|schema)\b"),
    ]
    for tag, pattern in pattern_checks:
        if re.search(pattern, text):
            tags.append(tag)
            evidence.append(tag)

    for tag in _as_str_list(row.get("risk_tags")):
        if tag:
            tags.append(tag)
    if str(row.get("risk", "")).lower() == "high":
        tags.append("proposal_high_risk")
    tags.extend(_proposal_high_risk_fields(row))

    similarity = reject_buffer_similarity(row, rejected, threshold=duplicate_threshold)
    if similarity["duplicate_rejected"]:
        tags.append("duplicate_rejected")
        evidence.append("matched_rejected_buffer")

    paired_summary = _paired_seed_summary(paired_seed_table or [])
    if paired_summary["valid_count"] >= 3 and paired_summary["candidate_edge_rate"] < 0.5:
        tags.append("paired_seed_unstable")
        evidence.append("candidate_edge_rate_below_half")
    avg_delta = paired_summary.get("avg_score_delta")
    if avg_delta is not None and avg_delta <= 0 and paired_summary["candidate_wins"] > 0:
        tags.append("role_score_not_improved")
        evidence.append("non_positive_avg_score_delta")

    tags = _unique_str(tags)
    score = _overfit_score(tags)
    if score >= 0.75 or "seed_specific" in tags and "duplicate_rejected" in tags:
        gate_effect = "block"
        tags.append("overfit_high")
    elif score >= 0.35 or tags:
        gate_effect = "review_required"
    else:
        gate_effect = "allow"
    tags = _unique_str(tags)
    return {
        "overfit_risk_score": round(score, 4),
        "overfit_risk_tags": tags,
        "risk_tags": tags,
        "overfit_evidence": _unique_str(evidence),
        "gate_effect": gate_effect,
        "similarity": similarity,
    }


def assess_proposal_risk(
    proposal: SkillProposal | dict[str, Any],
    *,
    rejected: list[dict[str, Any]] | None = None,
    paired_seed_table: list[dict[str, Any]] | None = None,
    duplicate_threshold: float = 0.72,
) -> dict[str, Any]:
    """Combined reject-buffer similarity and overfit report for one proposal."""
    row = proposal.to_dict() if isinstance(proposal, SkillProposal) else dict(proposal or {})
    risk = detect_overfit_risk(
        row,
        paired_seed_table=paired_seed_table,
        rejected=rejected,
        duplicate_threshold=duplicate_threshold,
    )
    return {
        "proposal_id": str(row.get("proposal_id", "")),
        "target_file": str(row.get("target_file", "")),
        "review_status": normalize_proposal_review_status(row.get("review_status", row.get("status"))),
        "risk": str(row.get("risk", "")),
        **risk,
    }


def _proposal_decision_map(decisions: dict[str, Any] | list[dict[str, Any]] | None) -> dict[str, Any]:
    if not decisions:
        return {}
    if isinstance(decisions, dict):
        result: dict[str, Any] = {}
        for key, value in decisions.items():
            result[str(key)] = value
        return result
    result = {}
    if isinstance(decisions, list):
        for item in decisions:
            if not isinstance(item, dict):
                continue
            proposal_id = item.get("proposal_id") or item.get("id")
            if proposal_id:
                result[str(proposal_id)] = dict(item)
    return result


def _unique_str(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _first_present(mapping: Any, keys: tuple[str, ...], *, default_value: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default_value
    for key in keys:
        if key in mapping and mapping.get(key) is not None:
            return mapping.get(key)
    return default_value


def _collect_battle_games(run: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for source in (run.get("battle_games"), result.get("battle_games")):
        if isinstance(source, list):
            games.extend(dict(item) for item in source if isinstance(item, dict))
    for key, side in (("baseline_games", "baseline"), ("candidate_games", "candidate")):
        source = result.get(key)
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("side", side)
            games.append(row)
    return games


def _battle_game_side(game: dict[str, Any]) -> str:
    side = str(game.get("side") or game.get("variant") or "").strip().lower()
    if side in {"baseline", "candidate"}:
        return side
    text = " ".join(str(game.get(key) or "") for key in ("game_id", "source_game_id", "storage_run_type"))
    lowered = text.lower()
    if "candidate" in lowered:
        return "candidate"
    if "baseline" in lowered:
        return "baseline"
    return ""


def _infer_seed_from_game_id(value: Any) -> int | None:
    text = str(value or "")
    match = re.search(r"_(\d{3,})$", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _build_paired_seed_row(seed: Any, pair: dict[str, Any], *, role: str, target_team: str) -> dict[str, Any]:
    baseline = pair.get("baseline") if isinstance(pair.get("baseline"), dict) else None
    candidate = pair.get("candidate") if isinstance(pair.get("candidate"), dict) else None
    baseline_score = _extract_role_score(baseline, role) if baseline else None
    candidate_score = _extract_role_score(candidate, role) if candidate else None
    score_delta = (
        round(candidate_score - baseline_score, 6)
        if candidate_score is not None and baseline_score is not None
        else None
    )
    baseline_rankable = _game_rankable(baseline) if baseline else False
    candidate_rankable = _game_rankable(candidate) if candidate else False
    failure_reason = _paired_failure_reason(baseline, candidate, baseline_rankable, candidate_rankable)
    winner_side = _paired_winner_side(
        baseline,
        candidate,
        baseline_score=baseline_score,
        candidate_score=candidate_score,
        target_team=target_team,
        rankable=baseline_rankable and candidate_rankable,
    )
    return {
        "seed": seed,
        "baseline_game_id": baseline.get("game_id") if baseline else None,
        "candidate_game_id": candidate.get("game_id") if candidate else None,
        "baseline_winner": baseline.get("winner") if baseline else None,
        "candidate_winner": candidate.get("winner") if candidate else None,
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "score_delta": score_delta,
        "baseline_rankable": baseline_rankable,
        "candidate_rankable": candidate_rankable,
        "winner_side": winner_side,
        "failure_reason": failure_reason,
    }


def _extract_role_score(game: dict[str, Any] | None, role: str = "") -> float | None:
    if not isinstance(game, dict):
        return None
    for key in ("target_role_score", "target_role_role_weighted_score", "role_score", "avg_role_score"):
        if key in game:
            value = _nullable_float(game.get(key))
            if value is not None:
                return value
    summary = game.get("score_summary") if isinstance(game.get("score_summary"), dict) else {}
    for key in ("target_role_role_weighted_score", "target_role_score", "avg_role_score"):
        value = _nullable_float(summary.get(key))
        if value is not None:
            return value
    for key in ("by_role_category", "by_role_category_scores", "by_role"):
        by_role = summary.get(key) if isinstance(summary.get(key), dict) else game.get(key)
        if isinstance(by_role, dict) and role:
            value = _nullable_float(by_role.get(role))
            if value is not None:
                return value
    for key in ("player_scores", "scores"):
        value = _score_from_player_rows(game.get(key), role)
        if value is not None:
            return value
    return None


def _score_from_player_rows(rows: Any, role: str) -> float | None:
    if not isinstance(rows, list):
        return None
    scores: list[float] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if role and str(item.get("role") or "") != role:
            continue
        score = _nullable_float(item.get("role_score"))
        if score is not None:
            scores.append(score)
    if not scores:
        return None
    return round(sum(scores) / len(scores), 6)


def _nullable_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _game_rankable(game: dict[str, Any] | None) -> bool:
    if not isinstance(game, dict):
        return False
    if "rankable" in game:
        return bool(game.get("rankable"))
    winner = _normalize_winner_value(game.get("winner"))
    return not game.get("error") and winner not in {"", "unknown", "none"}


def _paired_failure_reason(
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    baseline_rankable: bool,
    candidate_rankable: bool,
) -> str:
    if baseline is None:
        return "missing_baseline_game"
    if candidate is None:
        return "missing_candidate_game"
    if not baseline_rankable:
        return str(baseline.get("error") or "baseline_unrankable")
    if not candidate_rankable:
        return str(candidate.get("error") or "candidate_unrankable")
    return ""


def _paired_winner_side(
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    *,
    baseline_score: float | None,
    candidate_score: float | None,
    target_team: str,
    rankable: bool,
) -> str:
    if not rankable:
        return "invalid"
    if baseline_score is not None and candidate_score is not None:
        if candidate_score > baseline_score:
            return "candidate"
        if baseline_score > candidate_score:
            return "baseline"
        return "tie"
    target = _normalize_winner_value(target_team)
    baseline_win = _normalize_winner_value((baseline or {}).get("winner")) == target if target else False
    candidate_win = _normalize_winner_value((candidate or {}).get("winner")) == target if target else False
    if candidate_win and not baseline_win:
        return "candidate"
    if baseline_win and not candidate_win:
        return "baseline"
    return "tie"


def _normalize_winner_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"villager", "village", "villagers", "good"}:
        return "villagers"
    if text in {"werewolf", "werewolves", "wolf", "wolves", "evil"}:
        return "werewolves"
    return text


def _paired_seed_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid_rows = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("baseline_rankable")
        and row.get("candidate_rankable")
        and row.get("winner_side") != "invalid"
    ]
    candidate_wins = sum(1 for row in valid_rows if row.get("winner_side") == "candidate")
    baseline_wins = sum(1 for row in valid_rows if row.get("winner_side") == "baseline")
    ties = sum(1 for row in valid_rows if row.get("winner_side") == "tie")
    deltas = [
        float(row["score_delta"]) for row in valid_rows
        if isinstance(row.get("score_delta"), (int, float))
    ]
    return {
        "seed_count": len(rows),
        "valid_count": len(valid_rows),
        "candidate_wins": candidate_wins,
        "baseline_wins": baseline_wins,
        "ties": ties,
        "candidate_edge_rate": round(candidate_wins / len(valid_rows), 6) if valid_rows else 0.0,
        "avg_score_delta": round(sum(deltas) / len(deltas), 6) if deltas else None,
    }


def _role_score_gate_summary(rows: list[dict[str, Any]], result: dict[str, Any]) -> dict[str, Any]:
    baseline_scores = [
        float(row["baseline_score"]) for row in rows
        if isinstance(row.get("baseline_score"), (int, float))
    ]
    candidate_scores = [
        float(row["candidate_score"]) for row in rows
        if isinstance(row.get("candidate_score"), (int, float))
    ]
    baseline_avg = _average_or_result(baseline_scores, result.get("baseline"))
    candidate_avg = _average_or_result(candidate_scores, result.get("candidate"))
    delta = (
        round(candidate_avg - baseline_avg, 6)
        if baseline_avg is not None and candidate_avg is not None
        else None
    )
    return {
        "baseline_avg": baseline_avg,
        "candidate_avg": candidate_avg,
        "delta": delta,
        "paired_score_count": min(len(baseline_scores), len(candidate_scores)),
    }


def _average_or_result(values: list[float], side_summary: Any) -> float | None:
    if values:
        return round(sum(values) / len(values), 6)
    if isinstance(side_summary, dict):
        for key in ("avg_role_score", "target_role_score", "target_role_role_weighted_score"):
            value = _nullable_float(side_summary.get(key))
            if value is not None:
                return value
    return None


def _decision_quality_summary_for_gate(
    rows: list[dict[str, Any]],
    run: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    from app.lib.score import compute_decision_quality_metrics

    baseline_games = [row.get("baseline") for row in _pair_rows_with_games(run, result)]
    candidate_games = [row.get("candidate") for row in _pair_rows_with_games(run, result)]
    if not baseline_games and not candidate_games:
        baseline_games = [row.get("baseline") for row in rows if isinstance(row.get("baseline"), dict)]
        candidate_games = [row.get("candidate") for row in rows if isinstance(row.get("candidate"), dict)]
    baseline = compute_decision_quality_metrics([g for g in baseline_games if isinstance(g, dict)])
    candidate = compute_decision_quality_metrics([g for g in candidate_games if isinstance(g, dict)])
    baseline_issue = _trust_decision_issue_rate(baseline)
    candidate_issue = _trust_decision_issue_rate(candidate)
    return {
        "baseline": {**baseline, "issue_rate": round(baseline_issue, 6)},
        "candidate": {**candidate, "issue_rate": round(candidate_issue, 6)},
        "delta": round(candidate_issue - baseline_issue, 6),
    }


def _pair_rows_with_games(run: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    games = _collect_battle_games(run, result)
    by_seed: dict[Any, dict[str, Any]] = {}
    for game in games:
        seed = game.get("seed")
        if seed is None:
            continue
        side = _battle_game_side(game)
        if side:
            by_seed.setdefault(seed, {})[side] = game
    return list(by_seed.values())


def _trust_decision_issue_rate(metrics: dict[str, Any]) -> float:
    rates = [
        metrics.get("fallback_rate"),
        metrics.get("llm_error_rate"),
        metrics.get("policy_skipped_rate"),
        metrics.get("invalid_response_rate"),
        metrics.get("default_action_rate"),
    ]
    return max((_as_float(rate, 0.0) for rate in rates), default=0.0)


def _proposal_rows(
    proposals: list[SkillProposal | dict[str, Any]] | None,
    run: dict[str, Any],
) -> list[SkillProposal | dict[str, Any]]:
    if proposals is not None:
        return list(proposals)
    value = run.get("proposals")
    if isinstance(value, dict) and isinstance(value.get("proposals"), list):
        return [item for item in value.get("proposals", []) if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _gate_thresholds(thresholds: dict[str, Any] | None) -> dict[str, Any]:
    values = dict(thresholds or {})
    min_paired = int(values.get("min_paired_valid_seeds", 4) or 0)
    return {
        "min_paired_valid_seeds": min_paired,
        "min_shadow_valid_seeds": int(values.get("min_shadow_valid_seeds", min_paired) or 0),
        "min_canary_valid_seeds": int(values.get("min_canary_valid_seeds", 8) or 0),
        "min_baseline_valid_seeds": int(values.get("min_baseline_valid_seeds", 16) or 0),
        "min_role_score_delta": float(values.get("min_role_score_delta", 0.0) or 0.0),
        "max_decision_issue_rate": float(values.get("max_decision_issue_rate", 0.10) or 0.0),
        "max_decision_issue_delta": float(values.get("max_decision_issue_delta", 0.05) or 0.0),
        "min_candidate_edge_rate": float(values.get("min_candidate_edge_rate", 0.50) or 0.0),
        "duplicate_similarity_threshold": float(values.get("duplicate_similarity_threshold", 0.72) or 0.0),
        "min_trust_bundle_completeness": float(values.get("min_trust_bundle_completeness", 1.0) or 0.0),
    }


def _scenario_replay_gate_summary(run: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    report = result.get("scenario_replay_report")
    if not isinstance(report, dict):
        report = run.get("scenario_replay_report") if isinstance(run.get("scenario_replay_report"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return {
        "schema_version": report.get("schema_version"),
        "execution_mode": str(report.get("execution_mode") or ""),
        "status": str(report.get("status") or "missing"),
        "verdict": str(summary.get("verdict") or report.get("verdict") or "missing"),
        "scenario_count": int(report.get("scenario_count", summary.get("scenario_count", 0)) or 0),
        "policy_violation_count": int(summary.get("policy_violation_count", 0) or 0),
        "contract_missing_count": int(summary.get("contract_missing_count", 0) or 0),
    }


def _gate_policy_versions(run: dict[str, Any], result: dict[str, Any], *, role: str = "") -> dict[str, str]:
    cfg = run.get("config") if isinstance(run.get("config"), dict) else {}
    snapshots = [item for item in run.get("scenario_snapshots", []) or [] if isinstance(item, dict)]
    first_snapshot = snapshots[0] if snapshots else {}

    def _first_text(*values: Any, default: str) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return default

    resolved_role = role or str(run.get("role") or "")
    return {
        "gate_policy_version": _first_text(
            cfg.get("gate_policy_version"),
            result.get("gate_policy_version"),
            default="promotion_gate_v2",
        ),
        "score_policy_version": _first_text(
            cfg.get("score_policy_version"),
            result.get("score_policy_version"),
            default="role_score_v1",
        ),
        "judge_policy_version": _first_text(
            cfg.get("judge_policy_version"),
            result.get("judge_policy_version"),
            first_snapshot.get("judge_policy_version"),
            default="judge_policy_v1",
        ),
        "rubric_version": _first_text(
            cfg.get("rubric_version"),
            result.get("rubric_version"),
            first_snapshot.get("rubric_version"),
            default=f"{resolved_role or 'role'}_rubric_v1",
        ),
    }


def _trust_bundle_completeness(
    run: dict[str, Any],
    result: dict[str, Any],
    *,
    proposal_rows: list[dict[str, Any]],
    paired_rows: list[dict[str, Any]],
    scenario_replay: dict[str, Any],
    policy_versions: dict[str, str],
) -> dict[str, Any]:
    checks = {
        "baseline_version": bool(run.get("parent_hash") or result.get("baseline_version")),
        "candidate_version": bool(run.get("candidate_hash") or result.get("candidate_version")),
        "training_evidence": bool(_game_ids(run.get("training_games"))),
        "proposal_ids": bool([row.get("proposal_id") for row in proposal_rows if row.get("proposal_id")]),
        "proposal_evidence": bool(proposal_rows) and all(_proposal_has_trust_evidence(row) for row in proposal_rows),
        "skill_diff": bool(_trust_bundle_diff_rows(run.get("diff")) or run.get("candidate_hash")),
        "paired_seed_table": bool(paired_rows) and _paired_seed_summary(paired_rows)["valid_count"] > 0,
        "scenario_replay": scenario_replay.get("scenario_count", 0) > 0 and scenario_replay.get("status") != "missing",
        "policy_versions": all(bool(str(value or "").strip()) for value in policy_versions.values()),
    }
    missing = [key for key, passed in checks.items() if not passed]
    score = round((len(checks) - len(missing)) / len(checks), 6) if checks else 1.0
    return {
        "schema_version": "trust_bundle_completeness_v1",
        "complete": not missing,
        "score": score,
        "checks": checks,
        "missing": missing,
    }


def _release_gate_v2(
    *,
    battle_passed: bool,
    blocked_reasons: list[str],
    review_reasons: list[str],
    paired_summary: dict[str, Any],
    role_score: dict[str, Any],
    decision_quality: dict[str, Any],
    scenario_replay: dict[str, Any],
    proposal_rows: list[dict[str, Any]],
    risk_tags: list[str],
    thresholds: dict[str, Any],
    trust_bundle_completeness: dict[str, Any],
) -> dict[str, Any]:
    reasons = _unique_str([*blocked_reasons, *review_reasons])
    review = list(review_reasons)
    block = list(blocked_reasons)
    if not battle_passed and "battle_not_significant" not in block:
        block.append("battle_not_significant")
    if scenario_replay.get("execution_mode") != "contract_only" and scenario_replay.get("policy_violation_count", 0) > 0:
        block.append("scenario_policy_violation")
    if "overfit_high" in risk_tags and "proposal_overfit_risk_high" not in block:
        block.append("proposal_overfit_risk_high")
    if not trust_bundle_completeness.get("complete"):
        review.append("trust_bundle_incomplete")
    if any(str(row.get("risk", "")).lower() == "medium" for row in proposal_rows):
        review.append("proposal_medium_risk")

    block = _unique_str(block)
    review = _unique_str(review)
    valid_count = int(paired_summary.get("valid_count", 0) or 0)
    if block:
        decision = "block"
    elif review:
        decision = "review_required"
    elif valid_count < int(thresholds.get("min_shadow_valid_seeds", 0) or 0):
        decision = "review_required"
        review.append("paired_valid_count_below_shadow_minimum")
    elif valid_count < int(thresholds.get("min_canary_valid_seeds", 0) or 0):
        decision = "shadow_candidate"
    elif valid_count < int(thresholds.get("min_baseline_valid_seeds", 0) or 0):
        decision = "canary_candidate"
    else:
        decision = "baseline_promote"
    return {
        "schema_version": "promotion_gate_v2",
        "decision": decision,
        "release_decision": decision,
        "block_reasons": block,
        "review_reasons": review,
        "reasons": _unique_str([*reasons, *block, *review]),
        "thresholds": dict(thresholds),
        "metrics": {
            "paired_valid_count": valid_count,
            "candidate_edge_rate": paired_summary.get("candidate_edge_rate"),
            "role_score_delta": role_score.get("delta"),
            "decision_issue_delta": decision_quality.get("delta"),
            "scenario_count": scenario_replay.get("scenario_count"),
            "trust_bundle_completeness": trust_bundle_completeness.get("score"),
        },
    }


def _proposal_has_trust_evidence(proposal: dict[str, Any]) -> bool:
    return (
        bool(str(proposal.get("hypothesis", "")).strip())
        and _non_empty_mapping(proposal.get("trigger_condition"))
        and _non_empty_mapping(proposal.get("metric_targets"))
        and bool(_as_str_list(proposal.get("evidence_game_ids")) or _proposal_source_game_ids(proposal, []))
    )


def _proposal_attribution_budget(run: dict[str, Any]) -> dict[str, Any]:
    cfg = run.get("config") if isinstance(run.get("config"), dict) else {}
    scenario_budget = int(
        cfg.get("attribution_scenario_budget", cfg.get("proposal_attribution_scenario_budget", 0))
        or 0
    )
    full_game_budget = int(
        cfg.get("attribution_full_game_budget", cfg.get("proposal_attribution_full_game_budget", 0))
        or 0
    )
    max_proposals = int(
        cfg.get("attribution_max_proposals", cfg.get("proposal_attribution_max_proposals", 2))
        or 0
    )
    min_paired = int(
        cfg.get(
            "attribution_min_paired_valid_seeds",
            cfg.get("proposal_attribution_min_paired_valid_seeds", 4),
        )
        or 0
    )
    if full_game_budget > 0:
        scope = "full_game"
    elif scenario_budget > 0:
        scope = "scenario_only"
    else:
        scope = "not_run"
    return {
        "enabled": bool(cfg.get("enable_proposal_attribution", True)),
        "budget_scope": scope,
        "scenario_budget": scenario_budget,
        "full_game_budget": full_game_budget,
        "max_proposals": max_proposals,
        "min_paired_valid_seeds_for_attribution": min_paired,
    }


def _proposal_attribution_row(
    proposal: dict[str, Any],
    risk: dict[str, Any],
    *,
    budget: dict[str, Any],
) -> dict[str, Any]:
    risk_tags = _unique_str([*_as_str_list(proposal.get("risk_tags")), *_as_str_list(risk.get("risk_tags"))])
    risk_level = str(proposal.get("risk") or risk.get("risk") or "").lower()
    requires_ablation = bool(
        risk_level in {"high", "medium"}
        or any(tag in {"duplicate_rejected", "overfit_high", "paired_seed_unstable"} for tag in risk_tags)
    )
    reasons: list[str] = []
    if risk_level in {"high", "medium"}:
        reasons.append(f"{risk_level}_risk")
    if "duplicate_rejected" in risk_tags:
        reasons.append("duplicate_rejected")
    if "overfit_high" in risk_tags:
        reasons.append("overfit_high")
    if "paired_seed_unstable" in risk_tags:
        reasons.append("paired_seed_unstable")
    if requires_ablation and not budget.get("scenario_budget") and not budget.get("full_game_budget"):
        reasons.append("ablation_budget_zero")
    return {
        "proposal_id": str(proposal.get("proposal_id") or ""),
        "target_file": str(proposal.get("target_file") or ""),
        "review_status": normalize_proposal_review_status(proposal.get("review_status", proposal.get("status"))),
        "status": "attribution_inconclusive",
        "reason": "ablation_not_run",
        "requires_ablation": requires_ablation,
        "ablation_priority": "required" if requires_ablation else "optional",
        "budget_scope": budget.get("budget_scope"),
        "estimated_contribution": None,
        "recommendation": "review" if requires_ablation else "attribution_inconclusive",
        "attribution_confidence": "none",
        "risk_tags": risk_tags,
        "reasons": _unique_str(reasons),
    }


def _trust_bundle_diff_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, SkillDiff):
            rows.append(item.to_dict())
        elif isinstance(item, dict):
            rows.append(dict(item))
    return rows


def _trust_bundle_ids(value: Any, *, fallback: list[Any] | None = None) -> list[str]:
    source = value if isinstance(value, list) else fallback or []
    return _unique_str(str(item) for item in source if item not in (None, ""))


def _game_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for item in value:
        if isinstance(item, dict):
            ids.append(str(item.get("game_id") or item.get("source_game_id") or "").strip())
        elif item not in (None, ""):
            ids.append(str(item))
    return _unique_str(ids)


def _scenario_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for item in value:
        if isinstance(item, dict):
            ids.append(str(item.get("scenario_id") or "").strip())
        elif item not in (None, ""):
            ids.append(str(item))
    return _unique_str(ids)


def _proposal_review_events(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for proposal in proposals:
        status = normalize_proposal_review_status(proposal.get("review_status", proposal.get("status")))
        if status == "proposed":
            continue
        events.append(
            {
                "proposal_id": proposal.get("proposal_id"),
                "decision": status,
                "review_reason": proposal.get("review_reason") or proposal.get("rejection_reason") or "",
                "reviewed_by": proposal.get("reviewed_by"),
                "reviewed_at": proposal.get("reviewed_at"),
            }
        )
    return events


def _sha256_json(value: Any) -> str:
    import hashlib

    return hashlib.sha256(compact_json(to_jsonable(value)).encode("utf-8")).hexdigest()


def _gate_report_id(run_id: str, report: dict[str, Any]) -> str:
    prefix = f"gate_{run_id}" if run_id else "gate"
    return f"{prefix}_{_sha256_json(report)[:12]}"


def _trust_bundle_id(run_id: str, bundle_hash: str) -> str:
    prefix = f"trust_bundle_{run_id}" if run_id else "trust_bundle"
    return f"{prefix}_{bundle_hash[:12]}"


def _attribution_report_id(run_id: str, report: Any) -> str:
    prefix = f"attribution_{run_id}" if run_id else "attribution"
    payload = report if isinstance(report, dict) else {}
    return f"{prefix}_{_sha256_json(payload)[:12]}"


def _repro_command(run: dict[str, Any]) -> str:
    for key in ("repro_command", "reproduction_command"):
        value = run.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    run_id = str(run.get("run_id") or "").strip()
    suffix = f" for run_id={run_id}" if run_id else ""
    return f"not_available: dedicated evolution replay CLI is not implemented{suffix}"


def _trust_bundle_manifest_completeness(bundle: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "run_id": bool(bundle.get("run_id")),
        "role": bool(bundle.get("role")),
        "baseline_version": bool(bundle.get("baseline_version")),
        "candidate_version": bool(bundle.get("candidate_version")),
        "training_game_ids": bool(bundle.get("training_game_ids")),
        "scenario_ids": bool(bundle.get("scenario_ids")),
        "battle_pair_seeds": bool(bundle.get("battle_pair_seeds")),
        "proposal_ids": bool(bundle.get("proposal_ids")),
        "diff_hash": bool(bundle.get("diff_hash")),
        "gate_report_id": bool(bundle.get("gate_report_id")),
        "policy_versions": all(
            bool(bundle.get(key))
            for key in ("gate_policy_version", "score_policy_version", "judge_policy_version", "rubric_version")
        ),
        "thresholds": bool(bundle.get("thresholds")),
        "rollback_target": bool(bundle.get("rollback_target")),
        "repro_command": bool(bundle.get("repro_command")),
    }
    missing = [key for key, passed in checks.items() if not passed]
    score = round((len(checks) - len(missing)) / len(checks), 6) if checks else 1.0
    return {
        "complete": not missing,
        "score": score,
        "checks": checks,
        "missing": missing,
    }


def _proposal_risk_text(proposal: dict[str, Any]) -> str:
    parts = [
        proposal.get("target_file"),
        proposal.get("action_type"),
        proposal.get("section"),
        proposal.get("content"),
        proposal.get("rationale"),
        proposal.get("hypothesis"),
        proposal.get("problem_observation"),
        proposal.get("diff_intent"),
        proposal.get("failure_mode"),
        proposal.get("expected_metric"),
        compact_json(proposal.get("trigger_condition", {})),
        compact_json(proposal.get("expected_effect", {})),
        compact_json(proposal.get("metric_targets", {})),
    ]
    for key in ("diff", "before", "after"):
        value = proposal.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(str(part or "") for part in parts)


def _normalized_proposal_hash(proposal: dict[str, Any]) -> str:
    return _short_text_hash(_normalize_similarity_text(_proposal_risk_text(proposal)))


def _normalize_similarity_text(text: str) -> str:
    value = str(text or "").lower()
    value = re.sub(r"\bseed[_\s:#-]*\d+\b", " seed_n ", value)
    value = re.sub(r"\b(game|game_id|source_game_id)[_\s:#-]*[a-z0-9_-]+\b", " game_n ", value)
    value = re.sub(r"\b(player|p)[_\s:#-]*\d+\b", " player_n ", value)
    value = re.sub(r"\d+\s*号", " player_n ", value)
    value = re.sub(r"\d+", " n ", value)
    value = re.sub(r"[^\w\u4e00-\u9fff]+", " ", value)
    return " ".join(value.split())


def _similarity_tokens(proposal: dict[str, Any]) -> set[str]:
    text = _normalize_similarity_text(_proposal_risk_text(proposal))
    return {token for token in text.split() if token and token != "n"}


def _proposal_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_hash = _normalized_proposal_hash(left)
    right_hash = _normalized_proposal_hash(right)
    same_target = str(left.get("target_file", "")) == str(right.get("target_file", "")) and bool(left.get("target_file"))
    same_action = str(left.get("action_type", "")) == str(right.get("action_type", "")) and bool(left.get("action_type"))
    if same_target and same_action and left_hash == right_hash:
        return 1.0
    left_tokens = _similarity_tokens(left)
    right_tokens = _similarity_tokens(right)
    if not left_tokens or not right_tokens:
        content_score = 0.0
    else:
        content_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    score = content_score * 0.75
    if same_target:
        score += 0.15
    if same_action:
        score += 0.10
    left_tags = set(_as_str_list(left.get("risk_tags")))
    right_tags = set(_as_str_list(right.get("risk_tags")))
    if left_tags and right_tags:
        score += 0.10 * (len(left_tags & right_tags) / len(left_tags | right_tags))
    return max(0.0, min(1.0, score))


def _compact_rejection_match(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "proposal_id": item.get("proposal_id"),
        "target_file": item.get("target_file"),
        "action_type": item.get("action_type"),
        "reason": item.get("review_reason") or item.get("rejection_reason") or item.get("reason"),
        "source_run_id": item.get("source_run_id"),
    }


def _overfit_score(tags: list[str]) -> float:
    weights = {
        "seed_specific": 0.35,
        "game_id_specific": 0.30,
        "player_specific": 0.25,
        "model_specific": 0.20,
        "database_specific": 0.20,
        "duplicate_rejected": 0.35,
        "paired_seed_unstable": 0.25,
        "role_score_not_improved": 0.20,
        "proposal_high_risk": 0.30,
        "role_identity": 0.20,
        "private_info": 0.20,
        "front_matter": 0.20,
        "global_policy": 0.20,
    }
    return min(1.0, sum(weights.get(tag, 0.10) for tag in set(tags)))


# ---------------------------------------------------------------------------
# Evolution config
# ---------------------------------------------------------------------------

@dataclass
class EvolutionConfig:
    training_games: int = 5
    battle_games: int = 4
    role_concurrency: int = 2
    game_concurrency: int = DEFAULT_GAME_CONCURRENCY
    llm_concurrency: int = 20
    llm_rpm: int = 60
    auto_promote: bool = True
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
    # Auto-promotion is stricter than battle significance: small A/B samples
    # may justify human review, but should not silently replace the baseline.
    promotion_min_completed_games: int = 8
    promotion_min_valid_game_rate: float = 0.85
    promotion_max_decision_issue_rate: float = 0.10
    promotion_min_proposal_quality: float = 0.60

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


# Defaults sourced from EvolutionConfig so the pipeline and config never drift.
_EVOLUTION_DEFAULTS = EvolutionConfig()


# ---------------------------------------------------------------------------
# Evolution state
# ---------------------------------------------------------------------------

class EvolutionStateManager:
    """PostgreSQL-backed per-role evolution run state access."""

    def __init__(self, root_dir: Path | str | None = None) -> None:
        self._legacy_root_dir = Path(root_dir) if root_dir is not None else None

    def run_dir(self, run_id: str) -> Path:
        """Return the legacy run directory location without creating files."""
        _validate_run_id(run_id)
        if self._legacy_root_dir is not None:
            return self._legacy_root_dir / run_id
        from app.config import DEFAULT_PATHS

        return DEFAULT_PATHS.evolution_dir / run_id

    def save_run(self, run: EvolutionRun) -> None:
        """Persist the current run state to PostgreSQL."""
        from app.util.time import beijing_now_iso
        from storage.evolution.state_gateway import EvolutionStateGateway
        from storage.interfaces import EvolutionRunData

        _validate_run_id(run.run_id)
        updated_at = beijing_now_iso()
        payload = to_jsonable(run.to_dict())
        payload["updated_at"] = updated_at
        payload["started_at"] = run.started_at or updated_at
        payload["finished_at"] = run.finished_at

        EvolutionStateGateway().save_run(
            EvolutionRunData(
                run_id=run.run_id,
                role=run.role,
                parent_hash=run.parent_hash,
                status=run.status,
                training_games=run.training_games,
                battle_games=run.battle_games,
                baseline_config=run.baseline_config,
                candidate_hash=run.candidate_hash,
                battle_result=run.battle_result,
                errors=list(run.errors),
                training_run_id=run.training_run_id,
                training_output_dir=run.training_output_dir,
                runtime_state=payload,
                started_at=run.started_at or updated_at,
                finished_at=run.finished_at,
            )
        )

    def load_run(self, run_id: str) -> EvolutionRun | None:
        """Load a persisted run by id from PostgreSQL."""
        _validate_run_id(run_id)
        from storage.evolution.state_gateway import EvolutionStateGateway

        stored = EvolutionStateGateway().get_run(run_id)
        if stored is None:
            return None
        return _evolution_run_from_storage(stored)

    def list_runs(self, role: str) -> list[EvolutionRun]:
        """List persisted runs for a role from PostgreSQL."""
        from storage.evolution.state_gateway import EvolutionStateGateway

        stored = EvolutionStateGateway().list_runs(role=role, limit=200)
        return [_evolution_run_from_storage(item) for item in stored]

    def scan_active_runs(self) -> list[EvolutionRun]:
        """Return non-terminal runs for recovery dashboards."""
        from storage.evolution.state_gateway import EvolutionStateGateway

        terminal = {
            EvolutionStatus.PROMOTED.value,
            EvolutionStatus.REJECTED.value,
            EvolutionStatus.FAILED.value,
        }
        stored = EvolutionStateGateway().list_runs(limit=200)
        return [
            _evolution_run_from_storage(item)
            for item in stored
            if str(item.status) not in terminal
        ]


def _evolution_run_from_storage(data: Any) -> EvolutionRun:
    runtime_state = getattr(data, "runtime_state", None)
    if isinstance(runtime_state, dict):
        return EvolutionRun.from_dict(runtime_state)
    return EvolutionRun(
        run_id=str(getattr(data, "run_id", "")),
        role=str(getattr(data, "role", "")),
        parent_hash=str(getattr(data, "parent_hash", "")),
        status=str(getattr(data, "status", "")),
        training_games=int(getattr(data, "training_games", 0) or 0),
        battle_games=int(getattr(data, "battle_games", 0) or 0),
        baseline_config=getattr(data, "baseline_config", None),
        candidate_hash=getattr(data, "candidate_hash", None),
        battle_result=getattr(data, "battle_result", None),
        errors=list(getattr(data, "errors", []) or []),
    )


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
    judge_summary = _compact_training_judge_summary(evidence.get("decision_judge"))
    if judge_summary:
        result["decision_judge"] = judge_summary
    return result


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _compact_training_key_decision(item: dict[str, Any]) -> dict[str, Any]:
    quote = str(item.get("reason") or item.get("public_text") or "")[:180]
    result = {
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
    judge = _compact_training_decision_judge(item.get("judge"))
    if judge:
        result["judge"] = judge
    return result


def _compact_training_judge_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
    metrics = value.get("metrics") if isinstance(value.get("metrics"), dict) else {}
    result: dict[str, Any] = {
        "status": value.get("status"),
        "reason": value.get("reason"),
        "average_score": summary.get("average_score"),
        "quality_counts": summary.get("quality_counts", {}),
        "top_mistake_tags": summary.get("top_mistake_tags", []),
        "top_rubric_misses": summary.get("top_rubric_misses", []),
        "related_skills": summary.get("related_skills", []),
        "degraded_reasons": value.get("degraded_reasons", []),
        "judged": metrics.get("judged", summary.get("judged")),
        "failed": metrics.get("failed"),
    }
    return {key: item for key, item in result.items() if item not in (None, "", [], {})}


def _compact_training_decision_judge(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {
        "score": value.get("score"),
        "quality": value.get("quality"),
        "reason": str(value.get("reason") or "")[:180],
        "mistake_tags": value.get("mistake_tags", []),
        "rubric_misses": value.get("rubric_misses", []),
        "related_skills": value.get("related_skills", []),
        "suggestion": str(value.get("suggestion") or "")[:180],
        "confidence": value.get("confidence"),
    }
    return {key: item for key, item in result.items() if item not in (None, "", [], {})}


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
                f"2. proposals: 最多 {max_proposals} 个最重要的修改，每条必须是一条可验证 hypothesis，且只表达一个行为变化\n"
                "   - target_file 必须从上方可修改文件清单逐字复制；新建用 action_type=create_skill\n"
                "   - action_type ∈ append_rule|rewrite_section|deprecate_rule|create_skill\n"
                "   - 已有文件只能使用其 evolution.allowed_actions 内的动作\n"
                "   - risk ∈ low|medium|high；high risk 只写入 trends，不进 proposals\n"
                "   - expected_direction ∈ improve|maintain|reduce\n"
                "   - 每个 proposal 必须填写 hypothesis、trigger_condition、expected_effect、metric_targets\n"
                "   - 每个 proposal 至少引用 2 个不同 game_id 作为 evidence_game_ids；若摘要含 key_decisions，"
                "evidence 必须带 decision_id、action_type 和 quote\n"
                "   - trigger_condition 不得写具体 seed、game_id、run_id 或玩家号，只能描述可泛化的局面模式\n"
                "   - 不要把多个规则打包进同一个 proposal\n\n"
                "输出 JSON schema:\n"
                "{\n"
                '  "trends": ["趋势1", "趋势2"],\n'
                '  "proposals": [\n'
                "    {\n"
                '      "proposal_id": "prop_001",\n'
                '      "target_file": "从清单逐字复制.md",\n'
                '      "action_type": "append_rule|rewrite_section|deprecate_rule|create_skill",\n'
                '      "title": "短标题",\n'
                '      "section": "目标章节(rewrite_section时必填)",\n'
                '      "hypothesis": "当触发条件出现时，采用该行为会改善目标指标",\n'
                '      "problem_observation": "跨局问题观察",\n'
                '      "trigger_condition": {"phase": ["day1"], "public_state": ["vote_split"], "actor_pattern": ["泛化模式"]},\n'
                '      "expected_effect": {"primary_metric": "role_score", "secondary_metrics": ["win_rate"], "expected_direction": "increase_role_score"},\n'
                '      "metric_targets": {"min_role_score_delta": 0.2, "max_decision_issue_rate_delta": -0.05},\n'
                '      "evidence_game_ids": ["g1", "g2"],\n'
                '      "counter_evidence_game_ids": [],\n'
                '      "diff_intent": "最小修改意图",\n'
                '      "content": "具体修改内容",\n'
                '      "rationale": "修改理由",\n'
                '      "confidence": 0.0,\n'
                '      "risk": "low|medium|high",\n'
                '      "risk_tags": [],\n'
                '      "failure_mode": "可能失败方式",\n'
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
    rejected: list[dict[str, Any]] | None = None,
    duplicate_threshold: float = 0.72,
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
    generated_proposal_ids: list[str] = []
    preflight_passed_proposal_ids: list[str] = []
    preflight_rejected_proposal_ids: list[str] = []
    preflight_reports: list[dict[str, Any]] = []
    for i, p in enumerate(proposals_raw):
        if not isinstance(p, dict):
            warnings.append(f"consolidate: dropped proposal #{i + 1}: proposal must be an object")
            continue
        evidence = [dict(e) for e in p.get("evidence", []) if isinstance(e, dict)]
        proposal_id = str(p.get("proposal_id", "") or f"{run_id or 'run'}_prop_{i + 1:03d}")
        generated_proposal_ids.append(proposal_id)
        proposal = SkillProposal(
            proposal_id=proposal_id,
            target_file=str(p.get("target_file", "")),
            action_type=str(p.get("action_type", "")),
            title=str(p.get("title", "")),
            section=str(p.get("section", "")),
            content=str(p.get("content", "")),
            rationale=str(p.get("rationale", "")),
            hypothesis=str(p.get("hypothesis", "")),
            problem_observation=str(p.get("problem_observation", "")),
            trigger_condition=dict(p.get("trigger_condition", {}) or {}) if isinstance(p.get("trigger_condition", {}), dict) else {},
            expected_effect=dict(p.get("expected_effect", {}) or {}) if isinstance(p.get("expected_effect", {}), dict) else {},
            metric_targets=dict(p.get("metric_targets", {}) or {}) if isinstance(p.get("metric_targets", {}), dict) else {},
            evidence_game_ids=_as_str_list(p.get("evidence_game_ids")),
            counter_evidence_game_ids=_as_str_list(p.get("counter_evidence_game_ids")),
            diff_intent=str(p.get("diff_intent", "")),
            confidence=_as_float(p.get("confidence"), 0.0),
            risk=str(p.get("risk", p.get("risk_level", "medium"))),
            risk_tags=_as_str_list(p.get("risk_tags")),
            failure_mode=str(p.get("failure_mode", "")),
            expected_metric=str(p.get("expected_metric", "")),
            expected_direction=str(p.get("expected_direction", "improve")),
            evidence=evidence,
            conflicts_with=[str(c) for c in p.get("conflicts_with", [])],
            status="proposed",
        )
        proposal.quality_score = score_proposal_quality(proposal, raw=p)
        preflight = preflight_proposal(
            proposal,
            p,
            rejected=rejected,
            duplicate_threshold=duplicate_threshold,
        )
        preflight_reports.append(preflight)
        if preflight["status"] != "passed":
            preflight_rejected_proposal_ids.append(proposal.proposal_id)
            warnings.append(
                f"consolidate: dropped proposal {proposal.proposal_id or f'#{i + 1}'}: "
                + "; ".join(preflight["reasons"])
            )
            continue
        preflight_passed_proposal_ids.append(proposal.proposal_id)
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
        generated_proposal_ids=generated_proposal_ids,
        preflight_passed_proposal_ids=preflight_passed_proposal_ids[:max_proposals],
        preflight_rejected_proposal_ids=preflight_rejected_proposal_ids,
        preflight_reports=preflight_reports,
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
    for key in ("source_games", "source_game_ids", "game_ids", "evidence_game_ids"):
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


def _non_empty_mapping(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(item not in (None, "", [], {}) for item in value.values())


def _proposal_policy_specific_tags(proposal: dict[str, Any]) -> list[str]:
    text = compact_json(
        {
            "trigger_condition": proposal.get("trigger_condition", {}),
            "hypothesis": proposal.get("hypothesis", ""),
            "content": proposal.get("content", ""),
            "diff_intent": proposal.get("diff_intent", ""),
        }
    ).lower()
    checks = [
        ("seed_specific", r"\bseed[_\s:#-]*\d+\b"),
        ("game_id_specific", r"\b(game_id|source_game_id|run_id)\b"),
        ("player_specific", r"\b(player|p)[_\s:#-]*\d+\b|\d+\s*号"),
    ]
    return [tag for tag, pattern in checks if re.search(pattern, text)]


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
    proposed_files = _sanitize_apply_output(
        current_skills,
        proposed_files,
        active,
        consolidation,
    )

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


def _record_apply_warning(consolidation: SkillConsolidation, message: str) -> None:
    if message not in consolidation.warnings:
        consolidation.warnings.append(message)


def _sanitize_apply_output(
    current_skills: dict[str, str],
    proposed_files: dict[str, str],
    eligible: list[SkillProposal],
    consolidation: SkillConsolidation,
) -> dict[str, str]:
    """Keep the baseline complete and discard model edits outside proposal scope."""
    from storage.interfaces import normalize_skill_text

    eligible_targets = {proposal.target_file for proposal in eligible}
    sanitized = dict(current_skills)

    for target in eligible_targets:
        if target in proposed_files:
            sanitized[target] = proposed_files[target]
        elif target in current_skills:
            _record_apply_warning(
                consolidation,
                f"apply: eligible target '{target}' missing from model output; preserved baseline content",
            )

    for fname, content in proposed_files.items():
        if fname in eligible_targets:
            continue
        old_content = current_skills.get(fname)
        if old_content is None:
            _record_apply_warning(
                consolidation,
                f"apply: ignored unauthorized file creation '{fname}'",
            )
        elif normalize_skill_text(old_content) != normalize_skill_text(content):
            _record_apply_warning(
                consolidation,
                f"apply: ignored unauthorized file modification '{fname}'",
            )

    return sanitized


def _filter_eligible(proposals: list[SkillProposal]) -> list[SkillProposal]:
    """Keep confidence >= threshold, risk != high, status == proposed, preflight not blocked."""
    eligible: list[SkillProposal] = []
    for p in proposals:
        if p.status != "proposed":
            continue
        if str(p.preflight_status or "").lower() in {"blocked", "failed", "rejected"}:
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
