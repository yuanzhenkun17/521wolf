"""Experience cards — per-role, per-game knowledge extraction.

After a game completes, each player gets an ExperienceCard summarizing
what happened, what went well, what went wrong, and what to try next time.

Cards are written to ``data/experiences/{role}/cards.jsonl`` for later
retrieval by long-term memory consolidation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.models import Role, Team

from agent.evaluation.review_enhanced import (
    GameReviewReport,
    MISTAKE_FALLBACK_USED,
    MISTAKE_ILLEGAL_ACTION,
    MISTAKE_POISONED_GOOD,
    MISTAKE_SHOT_GOOD,
    MISTAKE_WRONG_VOTE,
    PlayerReview,
)


@dataclass(slots=True)
class ExperienceDecision:
    """A single notable decision within an experience card."""

    day: int
    phase: str
    action_type: str
    selected_skills: list[str]
    context: str
    action: str
    expected_outcome: str
    actual_result: str
    lesson: str

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "phase": self.phase,
            "action_type": self.action_type,
            "selected_skills": self.selected_skills,
            "context": self.context,
            "action": self.action,
            "expected_outcome": self.expected_outcome,
            "actual_result": self.actual_result,
            "lesson": self.lesson,
        }


@dataclass(slots=True)
class ExperienceCard:
    """A post-game experience summary for one player in one game."""

    card_id: str
    game_id: str
    player_id: int
    role: str
    team: str
    outcome: str
    created_at: str
    summary: str
    situation_tags: list[str]
    key_decisions: list[ExperienceDecision]
    lessons: list[str]
    avoid_next_time: list[str]
    reusable_strategies: list[str]
    related_skills: list[str]
    evidence_decision_ids: list[str]
    score: float
    confidence: float

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "game_id": self.game_id,
            "player_id": self.player_id,
            "role": self.role,
            "team": self.team,
            "outcome": self.outcome,
            "created_at": self.created_at,
            "summary": self.summary,
            "situation_tags": self.situation_tags,
            "key_decisions": [kd.to_dict() for kd in self.key_decisions],
            "lessons": self.lessons,
            "avoid_next_time": self.avoid_next_time,
            "reusable_strategies": self.reusable_strategies,
            "related_skills": self.related_skills,
            "evidence_decision_ids": self.evidence_decision_ids,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 2),
        }


# ── roles directory for experience output ──────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXPERIENCE_BASE_DIR = _PROJECT_ROOT / "data" / "experiences"

ROLE_DIR_MAP: dict[Role, str] = {
    Role.WEREWOLF: "werewolf",
    Role.SEER: "seer",
    Role.WITCH: "witch",
    Role.HUNTER: "hunter",
    Role.VILLAGER: "villager",
    Role.GUARD: "guard",
    Role.WHITE_WOLF_KING: "white_wolf_king",
}


# ── extraction ─────────────────────────────────────────────────────────────


def extract_experiences(
    game_id: str,
    roles: dict[int, Role],
    agent_decisions: dict[int, list[dict]],
    review: GameReviewReport,
    winner_team: str,
) -> list[ExperienceCard]:
    """Build one ExperienceCard per player from review + decision data.

    Args:
        game_id: Game identifier.
        roles: Player id → Role mapping (with final identity).
        agent_decisions: Per-player raw decision records.
        review: Enhanced game review report.
        winner_team: ``"werewolves"`` or ``"villagers"``.

    Returns:
        One ExperienceCard per player.
    """
    cards: list[ExperienceCard] = []

    for player_id, role in sorted(roles.items()):
        decisions = agent_decisions.get(player_id, [])
        player_review = review.player_scores.get(player_id)
        outcome = _player_outcome(role, winner_team)

        # Situation tags from mistakes and role
        tags = _extract_situation_tags(player_id, role, decisions, player_review, outcome)

        # Key decisions worth remembering
        key_decisions = _extract_key_decisions(player_id, role, decisions)

        # Lessons derived from review mistakes + low-score areas
        lessons = _extract_lessons(player_id, role, player_review)
        avoid = _extract_avoid_next_time(player_id, role, player_review)
        strategies = _extract_reusable_strategies(player_id, role, player_review)

        # Related skills from the decisions
        related_skills = _extract_related_skills(decisions)

        # Evidence decision IDs (decisions with mistakes or highlights)
        evidence_ids = _extract_evidence_ids(decisions, player_review)

        # Overall score and confidence
        score = player_review.total_score if player_review else 5.0
        confidence = min(score / 10.0, 0.95)

        # Summary
        summary = _build_summary(player_id, role, outcome, score, lessons)

        card_id = f"{game_id}_p{player_id}_{role.value}"

        card = ExperienceCard(
            card_id=card_id,
            game_id=game_id,
            player_id=player_id,
            role=role.value,
            team=role.team.value,
            outcome=outcome,
            created_at=_now(),
            summary=summary,
            situation_tags=tags,
            key_decisions=key_decisions,
            lessons=lessons,
            avoid_next_time=avoid,
            reusable_strategies=strategies,
            related_skills=related_skills,
            evidence_decision_ids=evidence_ids,
            score=score,
            confidence=confidence,
        )
        cards.append(card)

    return cards


def write_experience_card(card: ExperienceCard, output_dir: Path | str | None = None) -> Path:
    """Write a single experience card to the per-role cards.jsonl file.

    Args:
        card: The experience card to persist.
        output_dir: Base output directory (defaults to ``EXPERIENCE_BASE_DIR``).

    Returns:
        Path to the cards.jsonl file written.
    """
    base = Path(output_dir) if output_dir else EXPERIENCE_BASE_DIR
    role_dir = base / card.role
    role_dir.mkdir(parents=True, exist_ok=True)
    path = role_dir / "cards.jsonl"

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(card.to_dict(), ensure_ascii=False) + "\n")

    return path


def write_game_experiences(
    cards: list[ExperienceCard],
    game_dir: Path | str,
    output_dir: Path | str | None = None,
) -> None:
    """Write all experience cards for a game.

    Writes individual JSON files to ``game_dir/experiences/`` and appends
    to the per-role cards.jsonl under ``output_dir``.
    """
    exp_dir = Path(game_dir) / "experiences"
    exp_dir.mkdir(parents=True, exist_ok=True)

    for card in cards:
        # Per-card JSON in game directory
        card_path = exp_dir / f"player_{card.player_id}_{card.role}.json"
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card.to_dict(), f, ensure_ascii=False, indent=2)

        # Append to per-role cards.jsonl
        write_experience_card(card, output_dir)


def load_role_cards(role: Role, base_dir: Path | str | None = None) -> list[dict]:
    """Load all experience cards for a given role from cards.jsonl.

    Args:
        role: Role to load cards for.
        base_dir: Base experience directory.

    Returns:
        List of card dicts (empty if file does not exist).
    """
    role_name = ROLE_DIR_MAP.get(role, role.value)
    base = Path(base_dir) if base_dir else EXPERIENCE_BASE_DIR
    path = base / role_name / "cards.jsonl"
    if not path.exists():
        return []

    cards: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cards.append(json.loads(line))
    return cards


# ── internal helpers ───────────────────────────────────────────────────────


def _player_outcome(role: Role, winner_team: str) -> str:
    w = winner_team.lower()
    if w in ("werewolves", "werewolf") or "werewolf" in w:
        return "win" if role.team is Team.WEREWOLVES else "lose"
    return "win" if role.team in (Team.VILLAGERS, Team.GODS) else "lose"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_situation_tags(
    player_id: int,
    role: Role,
    decisions: list[dict],
    player_review: PlayerReview | None,
    outcome: str = "unknown",
) -> list[str]:
    tags = [role.value]
    if player_review:
        for mt in player_review.mistake_types:
            if mt == MISTAKE_POISONED_GOOD:
                tags.append("poisoned_good")
            elif mt == MISTAKE_SHOT_GOOD:
                tags.append("shot_good")
            elif mt == MISTAKE_FALLBACK_USED:
                tags.append("fallback_used")
            elif mt == MISTAKE_WRONG_VOTE:
                tags.append("wrong_vote")
    for d in decisions:
        skill = d.get("selected_skills") or d.get("selected_skill", "")
        if "fake_seer" in skill and "fake_seer" not in tags:
            tags.append("fake_seer")
        if "claim" in skill and "claim" not in tags:
            tags.append("claim")
    if outcome == "win":
        tags.append("win")
    else:
        tags.append("lose")
    return tags[:6]


def _extract_key_decisions(
    player_id: int,
    role: Role,
    decisions: list[dict],
) -> list[ExperienceDecision]:
    """Pick the most notable decisions (mistakes, high-impact actions)."""
    notable: list[ExperienceDecision] = []
    for d in decisions:
        source = d.get("source", "")
        action_type = d.get("action_type", "")
        is_notable = (
            source == "fallback"
            or source == "policy_adjusted"
            or action_type in {"witch_act", "hunter_shoot", "werewolf_kill", "seer_check"}
        )
        if not is_notable:
            continue

        skills = d.get("selected_skills") or d.get("selected_skill", "")
        skill_list = [s.strip() for s in skills.split(",") if s.strip()]

        notable.append(ExperienceDecision(
            day=d.get("day", 0),
            phase=d.get("phase", ""),
            action_type=action_type,
            selected_skills=skill_list or ["unknown"],
            context=d.get("action_type", ""),
            action=f"target={d.get('selected_target')}, choice={d.get('selected_choice', '')}",
            expected_outcome="N/A",
            actual_result=d.get("source", "unknown"),
            lesson=_decision_lesson(d, role),
        ))

    return notable[:5]


def _decision_lesson(d: dict, role: Role) -> str:
    source = d.get("source", "")
    action = d.get("action_type", "")
    if source == "fallback":
        return f"{action} 使用了回退策略，需要检查输出格式"
    if source == "policy_adjusted":
        return f"{action} 被策略修正，需要检查推理准确性"
    if action == "witch_act" and d.get("selected_choice") == "poison":
        return f"女巫毒人决策需要更充分的证据"
    if action == "hunter_shoot":
        return f"猎人开枪决策需要更谨慎"
    return f"{action} 决策可以进一步优化"


def _extract_lessons(
    player_id: int,
    role: Role,
    player_review: PlayerReview | None,
) -> list[str]:
    lessons: list[str] = []
    if player_review:
        for mt in player_review.mistake_types:
            if mt == MISTAKE_FALLBACK_USED:
                lessons.append("模型输出格式需要更严格的约束")
            elif mt == MISTAKE_POISONED_GOOD:
                lessons.append("毒人前必须确认目标身份，避免毒杀神职")
            elif mt == MISTAKE_SHOT_GOOD:
                lessons.append("开枪前必须确认目标身份，避免带走队友")
            elif mt == MISTAKE_WRONG_VOTE:
                lessons.append("投票前需要更多票型分析和站边推理")
            elif mt == MISTAKE_ILLEGAL_ACTION:
                lessons.append("需要更清晰地理解技能使用条件和目标范围")
        if player_review.speech_score < 4.0:
            lessons.append("发言需要更清晰的逻辑链和证据支撑")
        if player_review.vote_score < 4.0:
            lessons.append("投票决策需要结合更多信息")
        if player_review.skill_score < 4.0:
            lessons.append("技能使用需要更谨慎，确认目标后再行动")
    return lessons[:4]


def _extract_avoid_next_time(
    player_id: int,
    role: Role,
    player_review: PlayerReview | None,
) -> list[str]:
    avoid: list[str] = []
    if player_review:
        for mt in player_review.mistake_types:
            if mt == MISTAKE_POISONED_GOOD:
                avoid.append("无充分证据时毒杀疑似神职目标")
            elif mt == MISTAKE_SHOT_GOOD:
                avoid.append("未确认身份时开枪")
            elif mt == MISTAKE_WRONG_VOTE:
                avoid.append("仅凭发言印象投票，忽略票型分析")
            elif mt == MISTAKE_FALLBACK_USED:
                avoid.append("输出格式不合规导致回退")
    return avoid[:3]


def _extract_reusable_strategies(
    player_id: int,
    role: Role,
    player_review: PlayerReview | None,
) -> list[str]:
    strategies: list[str] = []
    if player_review and player_review.outcome == "win":
        strategies.append("本局获胜策略可重复参考")
    if player_review and player_review.highlights:
        for h in player_review.highlights[:2]:
            strategies.append(h)
    if not strategies:
        strategies.append("需进一步积累经验")
    return strategies[:3]


def _extract_related_skills(decisions: list[dict]) -> list[str]:
    skills: set[str] = set()
    for d in decisions:
        skill_str = d.get("selected_skills") or d.get("selected_skill", "")
        for sk in skill_str.split(","):
            sk = sk.strip()
            if sk and sk != "unknown":
                skills.add(sk)
    return sorted(skills)


def _extract_evidence_ids(
    decisions: list[dict],
    player_review: PlayerReview | None,
) -> list[str]:
    ids: list[str] = []
    for i, d in enumerate(decisions):
        source = d.get("source", "")
        if source in ("fallback", "policy_adjusted"):
            ids.append(f"decision_{i}")
    return ids[:5]


def _build_summary(
    player_id: int,
    role: Role,
    outcome: str,
    score: float,
    lessons: list[str],
) -> str:
    lesson_text = lessons[0] if lessons else ""
    return f"玩家P{player_id}({role.value})本局{outcome}，综合评分{score:.1f}。{lesson_text}"
