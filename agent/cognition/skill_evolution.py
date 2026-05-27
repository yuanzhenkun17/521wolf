"""Skill proposal and optional patch application.

Long-term memory and dream reports are not skills by themselves. This module
turns high-confidence dream proposals into auditable proposal files and can
optionally append safe rules to Markdown skills.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.models import Role

from agent.cognition.dream import DreamReport, SkillEditProposal
from agent.skill_system.loader import parse_front_matter


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SKILL_ROOT = _PROJECT_ROOT / "skills"
DEFAULT_PROPOSAL_DIR = _PROJECT_ROOT / "data" / "skill_proposals"
DEFAULT_PATCH_DIR = _PROJECT_ROOT / "data" / "skill_patches"

ROLE_DIR_MAP: dict[Role, str] = {
    Role.WEREWOLF: "werewolf",
    Role.SEER: "seer",
    Role.WITCH: "witch",
    Role.HUNTER: "hunter",
    Role.VILLAGER: "villager",
    Role.GUARD: "guard",
    Role.WHITE_WOLF_KING: "white_wolf_king",
}

ALLOWED_OPERATIONS = {"append_rule", "rewrite_section", "deprecate_rule"}


@dataclass(slots=True)
class SkillProposal:
    proposal_id: str
    role: str
    skill: str
    operation: str
    proposal: str
    risk: str
    evidence_cards: list[str]
    confidence: float
    source: str = "dream"
    status: str = "pending"  # pending | rejected | applied
    reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "role": self.role,
            "skill": self.skill,
            "operation": self.operation,
            "proposal": self.proposal,
            "risk": self.risk,
            "evidence_cards": self.evidence_cards,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "status": self.status,
            "reason": self.reason,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class SkillPatchRecord:
    patch_id: str
    role: str
    skill: str
    operation: str
    proposal_id: str
    skill_path: str
    applied_at: str
    inserted_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "role": self.role,
            "skill": self.skill,
            "operation": self.operation,
            "proposal_id": self.proposal_id,
            "skill_path": self.skill_path,
            "applied_at": self.applied_at,
            "inserted_text": self.inserted_text,
        }


def proposals_from_dream(
    report: DreamReport,
    *,
    min_confidence: float = 0.75,
    min_evidence_cards: int = 1,
) -> list[SkillProposal]:
    """Filter a dream report into auditable skill proposals."""
    proposals: list[SkillProposal] = []
    seen: set[tuple[str, str, str]] = set()
    for item in report.skill_edit_proposals:
        normalized = _normalize_dream_proposal(item)
        key = (normalized.skill, normalized.operation, normalized.proposal)
        if key in seen:
            continue
        seen.add(key)

        reason = _rejection_reason(
            normalized,
            min_confidence=min_confidence,
            min_evidence_cards=min_evidence_cards,
        )
        status = "rejected" if reason else "pending"
        proposals.append(SkillProposal(
            proposal_id=_proposal_id(report.role, normalized.skill, normalized.proposal),
            role=report.role,
            skill=normalized.skill,
            operation=normalized.operation,
            proposal=normalized.proposal,
            risk=normalized.risk,
            evidence_cards=normalized.evidence_cards,
            confidence=normalized.confidence,
            status=status,
            reason=reason,
        ))
    return proposals


def write_skill_proposals(
    proposals: list[SkillProposal],
    *,
    output_dir: Path | str | None = None,
) -> tuple[Path, Path] | None:
    """Write proposal JSON and Markdown files. Returns None for empty input."""
    if not proposals:
        return None
    role = proposals[0].role
    base = Path(output_dir) if output_dir else DEFAULT_PROPOSAL_DIR / role
    base.mkdir(parents=True, exist_ok=True)
    stem = f"proposal_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    json_path = base / f"{stem}.json"
    md_path = base / f"{stem}.md"
    data = [proposal.to_dict() for proposal in proposals]
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_proposals_markdown(proposals), encoding="utf-8")
    return json_path, md_path


def apply_skill_proposals(
    proposals: list[SkillProposal],
    *,
    target_skill_root: Path | str,
    audit_skill_root: Path | str | None = None,
    patch_dir: Path | str | None = None,
    min_confidence: float = 0.75,
    min_evidence_cards: int = 3,
) -> list[SkillPatchRecord]:
    """Append safe proposal rules to Markdown skills.

    Only ``append_rule`` is applied automatically. Other operations remain
    proposal-only because they require human review.
    """
    root = Path(target_skill_root)
    read_root = Path(audit_skill_root) if audit_skill_root else root
    records: list[SkillPatchRecord] = []
    for proposal in proposals:
        reason = _rejection_reason(
            proposal,
            min_confidence=min_confidence,
            min_evidence_cards=min_evidence_cards,
        )
        if reason or proposal.operation != "append_rule":
            continue
        skill_path = find_skill_path(proposal.role, proposal.skill, skill_root=read_root)
        if skill_path is None:
            continue
        text = skill_path.read_text(encoding="utf-8")
        # Check evolvable flag — skip non-evolvable skills
        front, _ = parse_front_matter(text)
        if not front.get("evolvable", False):
            continue
        inserted = _format_inserted_rule(proposal)
        if _rule_already_present(text, proposal.proposal):
            continue
        # Write to target_skill_root, not audit_skill_root
        if audit_skill_root:
            try:
                rel = skill_path.relative_to(read_root)
            except ValueError:
                rel = skill_path.name
            write_path = root / rel
        else:
            write_path = skill_path
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(text.rstrip() + "\n\n" + inserted + "\n", encoding="utf-8")
        record = SkillPatchRecord(
            patch_id=_proposal_id(proposal.role, proposal.skill, proposal.proposal),
            role=proposal.role,
            skill=proposal.skill,
            operation=proposal.operation,
            proposal_id=proposal.proposal_id,
            skill_path=str(write_path),
            applied_at=datetime.now(timezone.utc).isoformat(),
            inserted_text=inserted,
        )
        records.append(record)
    if records:
        write_patch_records(records, output_dir=patch_dir)
    return records


def write_patch_records(
    records: list[SkillPatchRecord],
    *,
    output_dir: Path | str | None = None,
) -> tuple[Path, Path] | None:
    if not records:
        return None
    role = records[0].role
    base = Path(output_dir) if output_dir else DEFAULT_PATCH_DIR / role
    base.mkdir(parents=True, exist_ok=True)
    stem = f"patch_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    json_path = base / f"{stem}.json"
    md_path = base / f"{stem}.md"
    json_path.write_text(
        json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(_patches_markdown(records), encoding="utf-8")
    return json_path, md_path


def find_skill_path(
    role: Role | str,
    skill: str,
    *,
    skill_root: Path | str | None = None,
) -> Path | None:
    root = Path(skill_root) if skill_root else DEFAULT_SKILL_ROOT
    role_dir = ROLE_DIR_MAP.get(role, str(role)) if isinstance(role, Role) else str(role)
    candidates = list((root / role_dir).glob("*.md"))
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        if re.search(rf"^name:\s*{re.escape(skill)}\s*$", text, flags=re.MULTILINE):
            return path
    return None


def _normalize_dream_proposal(item: SkillEditProposal) -> SkillEditProposal:
    operation = item.operation if item.operation in ALLOWED_OPERATIONS else "append_rule"
    return SkillEditProposal(
        skill=item.skill.strip(),
        operation=operation,
        proposal=item.proposal.strip(),
        risk=item.risk.strip(),
        evidence_cards=list(dict.fromkeys(item.evidence_cards)),
        confidence=float(item.confidence or 0.0),
    )


def _rejection_reason(
    proposal: SkillProposal | SkillEditProposal,
    *,
    min_confidence: float,
    min_evidence_cards: int,
) -> str:
    if not proposal.skill:
        return "missing skill"
    if not proposal.proposal:
        return "missing proposal"
    if proposal.operation not in ALLOWED_OPERATIONS:
        return f"operation {proposal.operation!r} is not allowed"
    if proposal.confidence < min_confidence:
        return f"confidence {proposal.confidence:.3f} < {min_confidence:.3f}"
    if len(proposal.evidence_cards) < min_evidence_cards:
        return f"evidence_cards {len(proposal.evidence_cards)} < {min_evidence_cards}"
    return ""


def _format_inserted_rule(proposal: SkillProposal) -> str:
    evidence = ", ".join(proposal.evidence_cards) or "-"
    risk = proposal.risk or "-"
    return (
        "<!-- agent-skill-proposal:"
        f" {proposal.proposal_id} -->\n"
        "## 经验沉淀规则\n\n"
        f"- {proposal.proposal}\n"
        f"- 证据: {evidence}\n"
        f"- 置信度: {proposal.confidence:.1%}\n"
        f"- 风险: {risk}\n"
        "<!-- /agent-skill-proposal -->"
    )


def _rule_already_present(text: str, proposal_text: str) -> bool:
    normalized = _normalize_text(proposal_text)
    return normalized in _normalize_text(text)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _proposal_id(role: str, skill: str, proposal: str) -> str:
    raw = f"{role}:{skill}:{proposal}"
    slug = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+", "_", raw).strip("_")
    return slug[:96] or "proposal"


def _proposals_markdown(proposals: list[SkillProposal]) -> str:
    lines = ["# Skill Proposals", ""]
    for proposal in proposals:
        lines.extend([
            f"## {proposal.skill}",
            "",
            f"- ID: {proposal.proposal_id}",
            f"- Role: {proposal.role}",
            f"- Operation: {proposal.operation}",
            f"- Status: {proposal.status}",
            f"- Confidence: {proposal.confidence:.1%}",
            f"- Evidence: {', '.join(proposal.evidence_cards) or '-'}",
            f"- Proposal: {proposal.proposal}",
            f"- Risk: {proposal.risk or '-'}",
        ])
        if proposal.reason:
            lines.append(f"- Reason: {proposal.reason}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _patches_markdown(records: list[SkillPatchRecord]) -> str:
    lines = ["# Skill Patches", ""]
    for record in records:
        lines.extend([
            f"## {record.skill}",
            "",
            f"- Patch ID: {record.patch_id}",
            f"- Proposal ID: {record.proposal_id}",
            f"- Skill path: {record.skill_path}",
            f"- Applied at: {record.applied_at}",
            "",
            "```markdown",
            record.inserted_text,
            "```",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"
