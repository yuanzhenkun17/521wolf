"""Long-term role memory built from post-game experience cards.

This module turns per-game ExperienceCard records into compact role-level
strategy memory.  The output is intentionally simple JSON/Markdown so it can
be inspected, versioned, and injected into prompts without a vector database.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.models import Role

from agent.cognition.experience import EXPERIENCE_BASE_DIR, ROLE_DIR_MAP, load_role_cards


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LONG_MEMORY_BASE_DIR = _PROJECT_ROOT / "data" / "long_memory"
PLACEHOLDER_TEXTS = {
    "本局无显著失误，继续保持",
    "继续保持当前策略",
}


@dataclass(slots=True)
class StrategyPrinciple:
    """A consolidated strategic lesson for a role."""

    title: str
    description: str
    evidence_count: int
    confidence: float
    source_cards: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "evidence_count": self.evidence_count,
            "confidence": round(self.confidence, 3),
            "source_cards": self.source_cards,
        }


@dataclass(slots=True)
class RoleLongTermMemory:
    """Consolidated long-term strategy memory for one role."""

    role: str
    generated_at: str
    source_card_count: int
    win_rate: float
    avg_score: float
    effective_strategies: list[StrategyPrinciple] = field(default_factory=list)
    recurring_mistakes: list[StrategyPrinciple] = field(default_factory=list)
    situational_rules: list[StrategyPrinciple] = field(default_factory=list)
    deprecated_rules: list[str] = field(default_factory=list)
    skill_update_suggestions: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "generated_at": self.generated_at,
            "source_card_count": self.source_card_count,
            "win_rate": round(self.win_rate, 3),
            "avg_score": round(self.avg_score, 2),
            "effective_strategies": [p.to_dict() for p in self.effective_strategies],
            "recurring_mistakes": [p.to_dict() for p in self.recurring_mistakes],
            "situational_rules": [p.to_dict() for p in self.situational_rules],
            "deprecated_rules": self.deprecated_rules,
            "skill_update_suggestions": self.skill_update_suggestions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# {self.role} Long-Term Memory",
            "",
            f"- Source cards: {self.source_card_count}",
            f"- Win rate: {self.win_rate:.1%}",
            f"- Average score: {self.avg_score:.2f}",
            f"- Generated at: {self.generated_at}",
            "",
            "## Effective Strategies",
            "",
        ]
        lines.extend(_principles_md(self.effective_strategies))
        lines.extend(["", "## Recurring Mistakes", ""])
        lines.extend(_principles_md(self.recurring_mistakes))
        lines.extend(["", "## Situational Rules", ""])
        lines.extend(_principles_md(self.situational_rules))
        if self.deprecated_rules:
            lines.extend(["", "## Deprecated / Low-Value Rules", ""])
            for rule in self.deprecated_rules:
                lines.append(f"- {rule}")
        if self.skill_update_suggestions:
            lines.extend(["", "## Skill Update Suggestions", ""])
            for skill, suggestions in sorted(self.skill_update_suggestions.items()):
                lines.append(f"### {skill}")
                for suggestion in suggestions:
                    lines.append(f"- {suggestion}")
                lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def consolidate_role_memory(
    role: Role,
    *,
    experience_dir: Path | str | None = None,
    min_evidence: int = 1,
    max_items: int = 8,
) -> RoleLongTermMemory:
    """Build long-term memory for one role from stored experience cards."""
    cards = load_role_cards(role, base_dir=experience_dir or EXPERIENCE_BASE_DIR)
    role_name = _role_name(role)
    if not cards:
        return RoleLongTermMemory(
            role=role_name,
            generated_at=_now(),
            source_card_count=0,
            win_rate=0.0,
            avg_score=0.0,
        )

    wins = sum(1 for card in cards if card.get("outcome") == "win")
    scores = [_as_float(card.get("score"), 0.0) for card in cards]

    effective = _principles_from_counter(
        _collect_counter(cards, "reusable_strategies"),
        title_prefix="有效策略",
        min_evidence=min_evidence,
        max_items=max_items,
    )
    mistakes = _principles_from_counter(
        _collect_counter(cards, "lessons"),
        title_prefix="高频教训",
        min_evidence=min_evidence,
        max_items=max_items,
    )
    situational = _principles_from_counter(
        _collect_counter(cards, "avoid_next_time"),
        title_prefix="避免策略",
        min_evidence=min_evidence,
        max_items=max_items,
    )

    deprecated = [
        p.description for p in situational
        if p.evidence_count >= max(min_evidence, 2)
    ][:max_items]

    suggestions = _skill_update_suggestions(cards, mistakes, situational)

    return RoleLongTermMemory(
        role=role_name,
        generated_at=_now(),
        source_card_count=len(cards),
        win_rate=wins / len(cards),
        avg_score=sum(scores) / len(scores) if scores else 0.0,
        effective_strategies=effective,
        recurring_mistakes=mistakes,
        situational_rules=situational,
        deprecated_rules=deprecated,
        skill_update_suggestions=suggestions,
    )


def consolidate_all_roles(
    *,
    experience_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    min_evidence: int = 1,
) -> dict[str, RoleLongTermMemory]:
    """Consolidate and write long-term memory for all known roles."""
    result: dict[str, RoleLongTermMemory] = {}
    for role in ROLE_DIR_MAP:
        memory = consolidate_role_memory(
            role,
            experience_dir=experience_dir,
            min_evidence=min_evidence,
        )
        result[memory.role] = memory
        write_role_memory(memory, output_dir=output_dir)
    return result


def write_role_memory(
    memory: RoleLongTermMemory,
    *,
    output_dir: Path | str | None = None,
) -> tuple[Path, Path]:
    """Write role long-term memory to JSON and Markdown."""
    base = Path(output_dir) if output_dir else LONG_MEMORY_BASE_DIR
    base.mkdir(parents=True, exist_ok=True)
    json_path = base / f"{memory.role}.json"
    md_path = base / f"{memory.role}.md"
    json_path.write_text(
        json.dumps(memory.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(memory.to_markdown(), encoding="utf-8")
    return json_path, md_path


def write_memory_candidate(
    memory: RoleLongTermMemory,
    *,
    output_dir: Path | str,
) -> Path:
    """Write memory candidate JSON for version management."""
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    json_path = base / f"{memory.role}.json"
    json_path.write_text(
        json.dumps(memory.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return json_path


def load_role_memory(
    role: Role | str,
    *,
    memory_dir: Path | str | None = None,
) -> RoleLongTermMemory | None:
    """Load consolidated long-term memory for a role if it exists."""
    role_name = _role_name(role)
    path = (Path(memory_dir) if memory_dir else LONG_MEMORY_BASE_DIR) / f"{role_name}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return _memory_from_dict(data)


def long_memory_prompt_hints(
    role: Role | str,
    *,
    action_type: str | None = None,
    memory_dir: Path | str | None = None,
    limit: int = 5,
) -> list[str]:
    """Return compact role strategy hints suitable for prompt injection."""
    memory = load_role_memory(role, memory_dir=memory_dir)
    if memory is None or memory.source_card_count == 0:
        return []

    candidates: list[str] = []
    for principle in memory.effective_strategies:
        candidates.append(f"可复用策略: {principle.description}")
    for principle in memory.recurring_mistakes:
        candidates.append(f"避免重复失误: {principle.description}")
    for principle in memory.situational_rules:
        candidates.append(f"局势规则: {principle.description}")

    if action_type:
        filtered = [
            item for item in candidates
            if action_type in item or _action_keyword(action_type) in item
        ]
        if filtered:
            candidates = filtered + [item for item in candidates if item not in filtered]

    return candidates[:limit]


def _collect_counter(cards: list[dict], field_name: str) -> dict[str, dict]:
    grouped: dict[str, dict] = defaultdict(lambda: {"count": 0, "cards": []})
    for card in cards:
        card_id = str(card.get("card_id") or "")
        for item in card.get(field_name, []) or []:
            text = str(item).strip()
            if not text or text in PLACEHOLDER_TEXTS:
                continue
            grouped[text]["count"] += 1
            if card_id:
                grouped[text]["cards"].append(card_id)
    return grouped


def _principles_from_counter(
    grouped: dict[str, dict],
    *,
    title_prefix: str,
    min_evidence: int,
    max_items: int,
) -> list[StrategyPrinciple]:
    if not grouped:
        return []
    max_count = max(item["count"] for item in grouped.values()) or 1
    rows = sorted(
        grouped.items(),
        key=lambda kv: (-kv[1]["count"], kv[0]),
    )
    principles: list[StrategyPrinciple] = []
    for index, (text, info) in enumerate(rows, 1):
        count = int(info["count"])
        if count < min_evidence:
            continue
        principles.append(
            StrategyPrinciple(
                title=f"{title_prefix} {index}",
                description=text,
                evidence_count=count,
                confidence=_principle_confidence(count, max_count, min_evidence),
                source_cards=list(dict.fromkeys(info["cards"]))[:10],
            )
        )
        if len(principles) >= max_items:
            break
    return principles


def _principle_confidence(count: int, max_count: int, min_evidence: int) -> float:
    if count < max(min_evidence, 2):
        return 0.45
    support = count / max(max_count, 1)
    sample_factor = min(count / 5.0, 1.0)
    return min(0.9, 0.35 + 0.35 * support + 0.2 * sample_factor)


def _skill_update_suggestions(
    cards: list[dict],
    mistakes: list[StrategyPrinciple],
    situational: list[StrategyPrinciple],
) -> dict[str, list[str]]:
    related: Counter[str] = Counter()
    for card in cards:
        for skill in card.get("related_skills", []) or []:
            skill_name = str(skill).strip()
            if skill_name:
                related[skill_name] += 1

    suggestions: dict[str, list[str]] = {}
    candidate_lessons = [p.description for p in mistakes[:3] + situational[:3]]
    for skill, _count in related.most_common(5):
        suggestions[skill] = [
            f"考虑加入经验规则：{lesson}"
            for lesson in candidate_lessons[:3]
        ]
    return suggestions


def _memory_from_dict(data: dict[str, Any]) -> RoleLongTermMemory:
    return RoleLongTermMemory(
        role=str(data.get("role", "")),
        generated_at=str(data.get("generated_at", "")),
        source_card_count=int(data.get("source_card_count", 0)),
        win_rate=_as_float(data.get("win_rate"), 0.0),
        avg_score=_as_float(data.get("avg_score"), 0.0),
        effective_strategies=[
            _principle_from_dict(item)
            for item in data.get("effective_strategies", [])
        ],
        recurring_mistakes=[
            _principle_from_dict(item)
            for item in data.get("recurring_mistakes", [])
        ],
        situational_rules=[
            _principle_from_dict(item)
            for item in data.get("situational_rules", [])
        ],
        deprecated_rules=[str(item) for item in data.get("deprecated_rules", [])],
        skill_update_suggestions={
            str(key): [str(item) for item in value]
            for key, value in data.get("skill_update_suggestions", {}).items()
        },
    )


def _principle_from_dict(data: dict[str, Any]) -> StrategyPrinciple:
    return StrategyPrinciple(
        title=str(data.get("title", "")),
        description=str(data.get("description", "")),
        evidence_count=int(data.get("evidence_count", 0)),
        confidence=_as_float(data.get("confidence"), 0.0),
        source_cards=[str(item) for item in data.get("source_cards", [])],
    )


def _principles_md(items: list[StrategyPrinciple]) -> list[str]:
    if not items:
        return ["- 暂无足够经验。"]
    lines: list[str] = []
    for item in items:
        lines.append(f"### {item.title}")
        lines.append("")
        lines.append(f"- {item.description}")
        lines.append(f"- Evidence: {item.evidence_count}")
        lines.append(f"- Confidence: {item.confidence:.1%}")
        if item.source_cards:
            lines.append(f"- Sources: {', '.join(item.source_cards[:5])}")
        lines.append("")
    return lines


def _role_name(role: Role | str) -> str:
    if isinstance(role, Role):
        return ROLE_DIR_MAP.get(role, role.value)
    return str(role)


def _action_keyword(action_type: str) -> str:
    mapping = {
        "witch_act": "毒",
        "hunter_shoot": "枪",
        "seer_check": "查验",
        "werewolf_kill": "刀",
        "exile_vote": "投票",
        "pk_vote": "投票",
        "speak": "发言",
    }
    return mapping.get(action_type, action_type)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
