"""Enhanced post-game review — detailed player scoring, mistake typing,
turning point detection, counterfactual analysis, and skill review.

Builds on top of ``review.py`` (which remains unchanged) with richer
dataclasses and analysis functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.models import Role, Team

from agent.evaluation.review import (
    AgentScores,
    GameReview,
    analyze_game,
    _did_survive,
    _get_role_of,
    _log_entries,
)


# ── standardized mistake types ───────────────────────────────────────────────

MISTAKE_ILLEGAL_ACTION = "illegal_action"
MISTAKE_POLICY_ADJUSTED = "policy_adjusted"
MISTAKE_FALLBACK_USED = "fallback_used"
MISTAKE_LOW_CONFIDENCE = "low_confidence"
MISTAKE_WRONG_VOTE = "wrong_vote"
MISTAKE_MISSED_WOLF = "missed_wolf"
MISTAKE_PROTECTED_WOLF = "protected_wolf"
MISTAKE_POISONED_GOOD = "poisoned_good"
MISTAKE_SHOT_GOOD = "shot_good"
MISTAKE_KILLED_TEAMMATE = "killed_teammate"
MISTAKE_BAD_CLAIM = "bad_claim"
MISTAKE_REVEALED_INFO = "revealed_private_info"
MISTAKE_IGNORED_SEER = "ignored_seer_check"
MISTAKE_IGNORED_VOTE = "ignored_vote_pattern"
MISTAKE_OVER_TRUSTED = "over_trusted_wolf"
MISTAKE_FAILED_COORDINATE = "failed_to_coordinate"


# ── enhanced data structures ──────────────────────────────────────────────────


@dataclass(slots=True)
class PlayerReview:
    """Detailed per-player review with multiple scoring dimensions."""

    player_id: int
    role: str
    team: str
    outcome: str  # "win" | "lose"
    total_score: float = 0.0
    speech_score: float = 0.0
    vote_score: float = 0.0
    skill_score: float = 0.0
    information_score: float = 0.0
    cooperation_score: float = 0.0
    highlights: list[str] = field(default_factory=list)
    mistakes: list[str] = field(default_factory=list)
    mistake_types: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "role": self.role,
            "team": self.team,
            "outcome": self.outcome,
            "total_score": round(self.total_score, 2),
            "scores": {
                "speech": round(self.speech_score, 2),
                "vote": round(self.vote_score, 2),
                "skill": round(self.skill_score, 2),
                "information": round(self.information_score, 2),
                "cooperation": round(self.cooperation_score, 2),
            },
            "highlights": self.highlights,
            "mistakes": self.mistakes,
            "mistake_types": self.mistake_types,
            "suggestions": self.suggestions,
        }


@dataclass(slots=True)
class TurningPoint:
    """A key moment that significantly influenced the game outcome."""

    day: int
    phase: str
    description: str
    impact: str  # "positive" | "negative" | "mixed"
    affected_team: str
    decision_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "phase": self.phase,
            "description": self.description,
            "impact": self.impact,
            "affected_team": self.affected_team,
        }


@dataclass(slots=True)
class DecisionMistake:
    """A specific mistaken decision with classification."""

    player_id: int
    role: str
    day: int
    phase: str
    action_type: str
    mistake_type: str
    description: str
    severity: str = "medium"  # "low" | "medium" | "high"

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "role": self.role,
            "day": self.day,
            "phase": self.phase,
            "action_type": self.action_type,
            "mistake_type": self.mistake_type,
            "description": self.description,
            "severity": self.severity,
        }


@dataclass(slots=True)
class SkillReview:
    """Summary of how a specific skill performed across decisions."""

    skill_name: str
    use_count: int = 0
    avg_confidence: float = 0.0
    success_count: int = 0
    fail_count: int = 0
    associated_mistakes: list[str] = field(default_factory=list)
    suggestion: str = ""

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "use_count": self.use_count,
            "avg_confidence": round(self.avg_confidence, 2),
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "associated_mistakes": self.associated_mistakes,
            "suggestion": self.suggestion,
        }


@dataclass(slots=True)
class Counterfactual:
    """What-if analysis for a critical decision."""

    decision_index: int
    player_id: int
    role: str
    fact: str
    counterfactual: str
    impact_assessment: str
    likelihood: str  # "likely" | "possible" | "unlikely"

    def to_dict(self) -> dict:
        return {
            "decision_index": self.decision_index,
            "player_id": self.player_id,
            "role": self.role,
            "fact": self.fact,
            "counterfactual": self.counterfactual,
            "impact_assessment": self.impact_assessment,
            "likelihood": self.likelihood,
        }


@dataclass(slots=True)
class GameReviewReport:
    """Complete enhanced review report for a single game."""

    game_id: str
    winner: str
    summary: str
    team_scores: dict[str, float]
    player_scores: dict[int, PlayerReview]
    key_turning_points: list[TurningPoint]
    mistakes: list[DecisionMistake]
    skill_summary: dict[str, SkillReview]
    counterfactuals: list[Counterfactual]
    suggestions: list[str]

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "winner": self.winner,
            "summary": self.summary,
            "team_scores": self.team_scores,
            "player_scores": {str(k): v.to_dict() for k, v in self.player_scores.items()},
            "key_turning_points": [tp.to_dict() for tp in self.key_turning_points],
            "mistakes": [m.to_dict() for m in self.mistakes],
            "skill_summary": {k: v.to_dict() for k, v in self.skill_summary.items()},
            "counterfactuals": [c.to_dict() for c in self.counterfactuals],
            "suggestions": self.suggestions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# {self.game_id} 复盘报告",
            "",
            "## 1. 基本信息",
            "",
            f"- **游戏ID**: {self.game_id}",
            f"- **胜利方**: {self.winner}",
            "",
            "## 2. 胜负概览",
            "",
            f"- **好人总分**: {self.team_scores.get('villagers', 0):.1f}",
            f"- **狼人总分**: {self.team_scores.get('werewolves', 0):.1f}",
            "",
            "## 3. 关键转折点",
            "",
        ]
        for tp in self.key_turning_points:
            emoji = {"positive": "正面", "negative": "负面", "mixed": "混合"}.get(tp.impact, "")
            lines.append(f"- [第{tp.day}天 {tp.phase}] {tp.description} ({emoji})")
        lines.append("")

        lines.append("## 4. 玩家评分")
        lines.append("")
        lines.append("| 玩家 | 角色 | 胜负 | 总分 | 发言 | 投票 | 技能 | 信息 | 协作 |")
        lines.append("|------|------|------|------|------|------|------|------|------|")
        for pid in sorted(self.player_scores):
            pr = self.player_scores[pid]
            lines.append(
                f"| P{pid} | {pr.role} | {pr.outcome} | {pr.total_score:.1f} | "
                f"{pr.speech_score:.1f} | {pr.vote_score:.1f} | {pr.skill_score:.1f} | "
                f"{pr.information_score:.1f} | {pr.cooperation_score:.1f} |"
            )
        lines.append("")

        lines.append("## 5. 关键错误")
        lines.append("")
        if self.mistakes:
            lines.append("| 玩家 | 类型 | 描述 | 严重程度 |")
            lines.append("|------|------|------|----------|")
            for m in self.mistakes:
                lines.append(f"| P{m.player_id}({m.role}) | {m.mistake_type} | {m.description} | {m.severity} |")
        else:
            lines.append("无显著关键错误。")
        lines.append("")

        lines.append("## 6. Skill 表现")
        lines.append("")
        for sk_name, sk in self.skill_summary.items():
            lines.append(f"- **{sk_name}**: 使用{sk.use_count}次, 平均置信度{sk.avg_confidence:.0%}")
            if sk.suggestion:
                lines.append(f"  - 建议: {sk.suggestion}")
        lines.append("")

        lines.append("## 7. 反事实推演")
        lines.append("")
        if self.counterfactuals:
            for c in self.counterfactuals:
                lines.append(f"- **事实**: {c.fact}")
                lines.append(f"  **反事实**: {c.counterfactual}")
                lines.append(f"  **评估**: {c.impact_assessment} (可能性: {c.likelihood})")
                lines.append("")
        else:
            lines.append("无非关键性反事实。")
            lines.append("")

        lines.append("## 8. 改进建议")
        lines.append("")
        for s in self.suggestions:
            lines.append(f"- {s}")
        lines.append("")

        return "\n".join(lines)


# ── enhanced analysis ─────────────────────────────────────────────────────────


def generate_enhanced_review(
    game_log: dict[str, Any],
    agent_decisions: dict[int, list[dict]],
    roles: dict[int, Role],
    winner_team: Team | str | None = None,
    game_id: str = "",
) -> GameReviewReport:
    """Generate an enhanced review report with detailed scoring and analysis.

    Uses the base ``analyze_game()`` for initial scoring, then adds
    richer player reviews, turning points, counterfactuals, and
    skill-level analysis.
    """
    # Get base review scores
    base_review = analyze_game(
        game_log=game_log,
        agent_decisions=agent_decisions,
        roles=roles,
        winner_team=winner_team,
        game_id=game_id,
    )

    winner_str = str(winner_team.value) if hasattr(winner_team, "value") else str(winner_team or "unknown")

    # Build player reviews
    player_reviews: dict[int, PlayerReview] = {}
    team_scores: dict[str, float] = {"villagers": 0.0, "werewolves": 0.0}
    villager_count = 0
    wolf_count = 0

    for pid, role in sorted(roles.items()):
        base_scores = base_review.agent_scores.get(pid)
        outcome = _player_outcome(pid, role, winner_str)
        score_team = "villagers" if role.team is not Team.WEREWOLVES else "werewolves"

        pr = PlayerReview(
            player_id=pid,
            role=role.value,
            team=score_team,
            outcome=outcome,
        )

        if base_scores:
            pr.speech_score = base_scores.speech_quality
            pr.vote_score = base_scores.vote_accuracy
            pr.skill_score = base_scores.skill_accuracy
            pr.cooperation_score = base_scores.team_contribution
            pr.total_score = base_scores.overall
            pr.highlights = list(base_scores.highlights)
            pr.mistakes = list(base_scores.mistakes)
            pr.mistake_types = _classify_mistakes(base_scores.mistakes, pid, role, agent_decisions)

        # Information score: based on known role type
        known_count = sum(1 for d in agent_decisions.get(pid, []) if d.get("action_type") == "seer_check")
        pr.information_score = min(known_count * 3, 10) if role is Role.SEER else 5.0

        # Suggestions
        pr.suggestions = _generate_player_suggestions(pid, role, pr)

        player_reviews[pid] = pr
        team_scores[score_team] = team_scores.get(score_team, 0) + pr.total_score
        if role.team is Team.WEREWOLVES:
            wolf_count += 1
        else:
            villager_count += 1

    # Normalize team scores
    if villager_count:
        team_scores["villagers"] = round(team_scores["villagers"] / villager_count, 2)
    if wolf_count:
        team_scores["werewolves"] = round(team_scores["werewolves"] / wolf_count, 2)

    # Turning points
    turning_points = _enhanced_turning_points(game_log, agent_decisions, roles, winner_str)

    # Mistakes
    mistakes = _collect_mistakes(agent_decisions, roles)

    # Skill review
    skill_summary = _analyze_skills(agent_decisions)

    # Counterfactuals
    counterfactuals = _generate_counterfactuals(mistakes, agent_decisions, roles)

    # Summary
    summary = _generate_summary(winner_str, team_scores, turning_points)

    # Suggestions
    suggestions = []
    for pr in player_reviews.values():
        suggestions.extend(pr.suggestions)
    suggestions = suggestions[:10]

    return GameReviewReport(
        game_id=game_id,
        winner=winner_str,
        summary=summary,
        team_scores=team_scores,
        player_scores=player_reviews,
        key_turning_points=turning_points,
        mistakes=mistakes,
        skill_summary=skill_summary,
        counterfactuals=counterfactuals,
        suggestions=suggestions,
    )


# ── helper functions ──────────────────────────────────────────────────────────


def _player_outcome(player_id: int, role: Role, winner_str: str) -> str:
    """Determine if this player's team won."""
    w = winner_str.lower()
    if w in ("werewolves", "werewolf") or "werewolf" in w:
        return "win" if role.team is Team.WEREWOLVES else "lose"
    return "win" if role.team in (Team.VILLAGERS, Team.GODS) else "lose"


def _classify_mistakes(
    mistake_texts: list[str],
    player_id: int,
    role: Role,
    agent_decisions: dict[int, list[dict]],
) -> list[str]:
    """Classify textual mistakes into standardized types."""
    types = []
    for text in mistake_texts:
        if "回退" in text:
            types.append(MISTAKE_FALLBACK_USED)
        elif "修正" in text:
            types.append(MISTAKE_POLICY_ADJUSTED)
        elif "置信度" in text:
            types.append(MISTAKE_LOW_CONFIDENCE)
        elif "毒" in text:
            types.append(MISTAKE_POISONED_GOOD)
        elif "带" in text or "开枪" in text:
            types.append(MISTAKE_SHOT_GOOD)
        elif "投票" in text:
            types.append(MISTAKE_WRONG_VOTE)
        else:
            types.append(MISTAKE_ILLEGAL_ACTION)
    return types


def _enhanced_turning_points(
    game_log: dict,
    agent_decisions: dict[int, list[dict]],
    roles: dict[int, Role],
    winner_str: str,
) -> list[TurningPoint]:
    """Detect key turning points with richer heuristics."""
    points: list[TurningPoint] = []
    entries = _log_entries(game_log)

    # Track known deaths from game log
    for entry in entries:
        if entry.get("event_type") == "death":
            target = entry.get("target")
            if target and target in roles:
                killed_role = roles[target]
                impact = "positive" if killed_role.team is Team.WEREWOLVES else "negative"
                desc = f"P{target}({killed_role.value}) 死亡"
                points.append(TurningPoint(
                    day=entry.get("day", 0),
                    phase=entry.get("phase", ""),
                    description=desc,
                    impact=impact,
                    affected_team="werewolves" if killed_role.team is Team.WEREWOLVES else "villagers",
                ))

    # Hunter shooting a good player
    for pid, decisions in agent_decisions.items():
        for d in decisions:
            action = d.get("action_type")
            if action == "hunter_shoot":
                target = d.get("selected_target")
                if target and target in roles:
                    t_role = roles[target]
                    desc = f"猎人P{pid} 开枪带走 P{target}({t_role.value})"
                    impact = "negative" if t_role.team is not Team.WEREWOLVES else "positive"
                    points.append(TurningPoint(
                        day=d.get("day", 0),
                        phase=d.get("phase", ""),
                        description=desc,
                        impact=impact,
                        affected_team="villagers",
                    ))

    # Witch poisoning
    for pid, decisions in agent_decisions.items():
        for d in decisions:
            if d.get("action_type") == "witch_act" and d.get("selected_choice") == "poison":
                target = d.get("selected_target")
                if target and target in roles:
                    t_role = roles[target]
                    desc = f"女巫P{pid} 毒杀 P{target}({t_role.value})"
                    impact = "positive" if t_role.team is Team.WEREWOLVES else "negative"
                    points.append(TurningPoint(
                        day=d.get("day", 0),
                        phase=d.get("phase", ""),
                        description=desc,
                        impact=impact,
                        affected_team="villagers",
                    ))

    # Werewolf kills a seer/witch/hunter
    for pid, decisions in agent_decisions.items():
        for d in decisions:
            if d.get("action_type") == "werewolf_kill":
                target = d.get("selected_target")
                if target and target in roles:
                    t_role = roles[target]
                    if t_role in (Role.SEER, Role.WITCH, Role.HUNTER):
                        desc = f"狼人刀杀 P{target}({t_role.value})"
                        impact = "positive" if ("werewolf" in winner_str.lower() or "werewolves" in winner_str.lower()) else "negative"
                        points.append(TurningPoint(
                            day=d.get("day", 0),
                            phase=d.get("phase", ""),
                            description=desc,
                            impact=impact,
                            affected_team="werewolves",
                        ))

    return points[:8]


def _collect_mistakes(
    agent_decisions: dict[int, list[dict]],
    roles: dict[int, Role],
) -> list[DecisionMistake]:
    """Collect and classify all mistakes across players."""
    mistakes: list[DecisionMistake] = []

    for pid, decisions in agent_decisions.items():
        role = roles.get(pid)
        role_name = role.value if role else "unknown"

        for d in decisions:
            source = d.get("source", "")

            # Fallback
            if source == "fallback":
                mistakes.append(DecisionMistake(
                    player_id=pid, role=role_name,
                    day=d.get("day", 0), phase=d.get("phase", ""),
                    action_type=d.get("action_type", ""),
                    mistake_type=MISTAKE_FALLBACK_USED,
                    description=f"{d.get('action_type')} 使用了回退策略",
                    severity="high",
                ))

            # Policy adjusted
            elif source == "policy_adjusted":
                adjustments = d.get("policy_adjustments", [])
                adj_text = "; ".join(adjustments) if adjustments else "target被修正"
                severity = "low" if "confidence" in str(d) else "medium"
                mistakes.append(DecisionMistake(
                    player_id=pid, role=role_name,
                    day=d.get("day", 0), phase=d.get("phase", ""),
                    action_type=d.get("action_type", ""),
                    mistake_type=MISTAKE_POLICY_ADJUSTED,
                    description=adj_text,
                    severity=severity,
                ))

            # Witch poisoned good
            if d.get("action_type") == "witch_act" and d.get("selected_choice") == "poison":
                target = d.get("selected_target")
                if target is not None and target in roles:
                    t_role = roles[target]
                    if t_role.team is not Team.WEREWOLVES:
                        mistakes.append(DecisionMistake(
                            player_id=pid, role=role_name,
                            day=d.get("day", 0), phase=d.get("phase", ""),
                            action_type="witch_act",
                            mistake_type=MISTAKE_POISONED_GOOD,
                            description=f"毒杀 P{target}({t_role.value})——毒错好人",
                            severity="high",
                        ))

            # Hunter shot good
            if d.get("action_type") == "hunter_shoot":
                target = d.get("selected_target")
                if target is not None and target in roles:
                    t_role = roles[target]
                    if t_role.team is not Team.WEREWOLVES:
                        mistakes.append(DecisionMistake(
                            player_id=pid, role=role_name,
                            day=d.get("day", 0), phase=d.get("phase", ""),
                            action_type="hunter_shoot",
                            mistake_type=MISTAKE_SHOT_GOOD,
                            description=f"带走 P{target}({t_role.value})——带错好人",
                            severity="high",
                        ))

    return mistakes


def _analyze_skills(agent_decisions: dict[int, list[dict]]) -> dict[str, SkillReview]:
    """Aggregate skill usage statistics across all players."""
    skill_map: dict[str, SkillReview] = {}

    for pid, decisions in agent_decisions.items():
        for d in decisions:
            skill_name = d.get("selected_skill", "")
            if not skill_name or skill_name == "unknown":
                continue

            # Split comma-separated skills
            for sk in skill_name.split(","):
                sk = sk.strip()
                if not sk:
                    continue
                if sk not in skill_map:
                    skill_map[sk] = SkillReview(skill_name=sk)
                skill_map[sk].use_count += 1
                skill_map[sk].avg_confidence += d.get("confidence", 0.5)
                source = d.get("source", "")
                if source == "fallback":
                    skill_map[sk].fail_count += 1
                elif source == "llm":
                    skill_map[sk].success_count += 1

    # Finalize averages
    for sk in skill_map.values():
        if sk.use_count > 0:
            sk.avg_confidence /= sk.use_count

    return skill_map


def _generate_counterfactuals(
    mistakes: list[DecisionMistake],
    agent_decisions: dict[int, list[dict]],
    roles: dict[int, Role],
) -> list[Counterfactual]:
    """Generate template-based counterfactual analysis for critical mistakes."""
    counterfactuals: list[Counterfactual] = []

    for m in mistakes:
        if m.mistake_type in (MISTAKE_POISONED_GOOD, MISTAKE_SHOT_GOOD):
            if m.mistake_type == MISTAKE_POISONED_GOOD:
                counterfactuals.append(Counterfactual(
                    decision_index=0,
                    player_id=m.player_id,
                    role=m.role,
                    fact=f"女巫P{m.player_id}毒杀{m.description.split('——')[0] if '——' in m.description else m.description}",
                    counterfactual=f"如果女巫没有毒杀该目标，好人阵营可能保留关键神职继续提供信息。该决策大概率降低了好人胜率。",
                    impact_assessment="该决策使好人阵营失去关键角色，信息链断裂，轮次落后。",
                    likelihood="likely",
                ))
            else:
                counterfactuals.append(Counterfactual(
                    decision_index=0,
                    player_id=m.player_id,
                    role=m.role,
                    fact=f"猎人P{m.player_id}开枪{m.description.split('——')[0] if '——' in m.description else m.description}",
                    counterfactual=f"如果猎人没有开枪带走该目标，好人阵营可以保留战斗力。该决策大概率降低了好人胜率。",
                    impact_assessment="该决策使好人阵营失去关键战力。",
                    likelihood="likely",
                ))

    return counterfactuals[:5]


def _generate_player_suggestions(player_id: int, role: Role, pr: PlayerReview) -> list[str]:
    """Generate per-player improvement suggestions."""
    suggestions = []
    if pr.speech_score < 4.0:
        suggestions.append(f"P{player_id}({role.value}) 发言质量偏低，建议增强发言逻辑完整性。")
    if pr.vote_score < 4.0:
        if role.team is not Team.WEREWOLVES:
            suggestions.append(f"P{player_id}({role.value}) 投票准确率低，建议增强票型分析和站边判断。")
    if pr.skill_score < 4.0:
        suggestions.append(f"P{player_id}({role.value}) 技能使用需优化，建议在 Prompt 中加强技能使用指导。")
    if MISTAKE_FALLBACK_USED in pr.mistake_types:
        suggestions.append(f"P{player_id}({role.value}) 有 fallback 发生，建议检查 Prompt 输出格式约束。")
    return suggestions


def _generate_summary(winner_str: str, team_scores: dict, turning_points: list[TurningPoint]) -> str:
    """Generate a brief game summary."""
    tp_count = len(turning_points)
    return (
        f"本局{winner_str}获胜。"
        f"共识别{tp_count}个关键转折点。"
        f"好人团队平均评分{team_scores.get('villagers', 0):.1f}，"
        f"狼人团队平均评分{team_scores.get('werewolves', 0):.1f}。"
    )
