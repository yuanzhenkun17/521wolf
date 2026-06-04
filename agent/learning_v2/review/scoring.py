"""Lightweight heuristic scoring for completed Werewolf games.

Provides ``analyze_game`` for producing a basic ``GameReview`` with per-player
scores, highlights, mistakes, turning points, and recommendations.  No LLM
calls are involved -- everything is pure heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.models import Role, Team
from agent.common import is_werewolf_win
from agent.common.action_types import (
    NIGHT_SKILL_ACTION_TYPES,
    SPEECH_ACTION_TYPES,
    VOTE_ACTION_TYPES,
)


# ---------------------------------------------------------------------------
# Lightweight review model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AgentScores:
    player_id: int
    role: str
    team: str
    survived: bool = False
    speech_quality: float = 0.0
    vote_accuracy: float = 0.0
    skill_accuracy: float = 0.0
    team_contribution: float = 0.0
    overall: float = 0.0
    highlights: list[str] = field(default_factory=list)
    mistakes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "role": self.role,
            "team": self.team,
            "survived": self.survived,
            "scores": {
                "speech_quality": round(self.speech_quality, 2),
                "vote_accuracy": round(self.vote_accuracy, 2),
                "skill_accuracy": round(self.skill_accuracy, 2),
                "team_contribution": round(self.team_contribution, 2),
                "overall": round(self.overall, 2),
            },
            "highlights": self.highlights,
            "mistakes": self.mistakes,
        }


@dataclass(slots=True)
class GameReview:
    game_id: str = ""
    winner: str = ""
    total_days: int = 0
    key_turning_points: list[str] = field(default_factory=list)
    agent_scores: dict[int, AgentScores] = field(default_factory=dict)
    global_mistakes: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "winner": self.winner,
            "total_days": self.total_days,
            "key_turning_points": self.key_turning_points,
            "agent_scores": {
                str(pid): scores.to_dict() for pid, scores in self.agent_scores.items()
            },
            "global_mistakes": self.global_mistakes,
            "recommendations": self.recommendations,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# 游戏复盘报告",
            f"",
            f"**游戏ID**: {self.game_id}",
            f"**胜利方**: {self.winner}",
            f"**总天数**: {self.total_days}",
            f"",
            "## 关键转折点",
        ]
        for tp in self.key_turning_points:
            lines.append(f"- {tp}")
        lines.append("")
        lines.append("## 玩家评分")
        lines.append("")
        lines.append("| 玩家 | 角色 | 发言 | 投票 | 技能 | 贡献 | 总分 | 存活 |")
        lines.append("|------|------|------|------|------|------|------|------|")
        for pid in sorted(self.agent_scores):
            s = self.agent_scores[pid]
            lines.append(
                f"| P{pid} | {s.role} | {s.speech_quality:.1f} | {s.vote_accuracy:.1f} | "
                f"{s.skill_accuracy:.1f} | {s.team_contribution:.1f} | {s.overall:.1f} | "
                f"{'Y' if s.survived else 'N'} |"
            )
        lines.append("")
        lines.append("## 高光与失误")
        for pid in sorted(self.agent_scores):
            s = self.agent_scores[pid]
            if s.highlights or s.mistakes:
                lines.append(f"### P{pid} ({s.role})")
                for h in s.highlights:
                    lines.append(f"- **高光**: {h}")
                for m in s.mistakes:
                    lines.append(f"- **失误**: {m}")
                lines.append("")
        if self.global_mistakes:
            lines.append("## 全局失误")
            for m in self.global_mistakes:
                lines.append(f"- {m}")
            lines.append("")
        if self.recommendations:
            lines.append("## 改进建议")
            for r in self.recommendations:
                lines.append(f"- {r}")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lightweight analyzer
# ---------------------------------------------------------------------------


def analyze_game(
    game_log: dict[str, Any],
    agent_decisions: dict[int, list[dict]],
    roles: dict[int, Role],
    winner_team: Team | str | None = None,
    game_id: str = "",
) -> GameReview:
    """Analyze a completed game and produce a structured review.

    Args:
        game_log: Game engine log entries (from GameLogger).
        agent_decisions: Per-player decision records (from AgentDecisionRecorder).
        roles: Mapping of player_id -> Role.
        winner_team: Winning team.
        game_id: Optional game identifier.
    """
    winner_str = str(winner_team.value) if hasattr(winner_team, "value") else str(winner_team or "unknown")
    review = GameReview(game_id=game_id, winner=winner_str)

    # Count days
    days = set()
    for decisions in agent_decisions.values():
        for d in decisions:
            if d.get("day"):
                days.add(d["day"])
    review.total_days = max(days) if days else 0

    # Score each agent
    for player_id, role in roles.items():
        decisions = agent_decisions.get(player_id, [])
        scores = _score_agent(player_id, role, decisions, winner_team, game_log, roles)
        review.agent_scores[player_id] = scores

    # Detect global mistakes
    review.global_mistakes = _detect_global_mistakes(review.agent_scores, game_log)
    review.key_turning_points = _detect_turning_points(game_log, agent_decisions)

    # Generate recommendations
    review.recommendations = _generate_recommendations(review)

    return review


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _score_agent(
    player_id: int,
    role: Role,
    decisions: list[dict],
    winner_team,
    game_log: dict,
    roles: dict[int, Role],
) -> AgentScores:
    scores = AgentScores(
        player_id=player_id,
        role=role.value,
        team=role.team.value,
        survived=did_survive(player_id, game_log),
    )

    if not decisions:
        return scores

    # Vote accuracy: voting against werewolves (for villagers) or against non-wolves (for wolves)
    vote_decisions = [d for d in decisions if d.get("action_type") in VOTE_ACTION_TYPES]
    correct_votes = 0
    for d in vote_decisions:
        target = d.get("selected_target")
        if target is not None:
            target_role = get_role_of(target, roles)
            if target_role is not None:
                is_correct = (role.team is not Team.WEREWOLVES and target_role.team is Team.WEREWOLVES) or \
                             (role.team is Team.WEREWOLVES and target_role.team is not Team.WEREWOLVES)
                if is_correct:
                    correct_votes += 1
    scores.vote_accuracy = correct_votes / len(vote_decisions) * 10 if vote_decisions else 5.0

    # Skill accuracy
    skill_decisions = [
        d for d in decisions
        if d.get("action_type") in NIGHT_SKILL_ACTION_TYPES
    ]
    correct_skills = 0
    for d in skill_decisions:
        target = d.get("selected_target")
        choice = d.get("selected_choice")
        action = d.get("action_type")
        if _is_good_skill_use(action, choice, target, role, game_log, roles):
            correct_skills += 1
    scores.skill_accuracy = correct_skills / len(skill_decisions) * 10 if skill_decisions else 5.0

    # Speech quality: based on confidence and source
    speech_decisions = [d for d in decisions if d.get("action_type") in SPEECH_ACTION_TYPES]
    if speech_decisions:
        # Speech quality based on source reliability, not LLM self-confidence
        fallback_rate = sum(1 for d in speech_decisions if d.get("source") == "fallback") / len(speech_decisions)
        scores.speech_quality = 7.0 * (1 - fallback_rate) + 2
    else:
        scores.speech_quality = 5.0

    # Team contribution
    wolves_win = is_werewolf_win(str(winner_team))
    w = str(winner_team).lower()
    villagers_win = w in ("villagers", "villager") or "villager" in w
    team_won = (
        (role.team is Team.WEREWOLVES and wolves_win) or
        (role.team is not Team.WEREWOLVES and villagers_win)
    )
    scores.team_contribution = 7.0 if team_won else 3.0
    if scores.survived and team_won:
        scores.team_contribution = 9.0

    # Overall
    scores.overall = (
        scores.speech_quality * 0.25 +
        scores.vote_accuracy * 0.25 +
        scores.skill_accuracy * 0.25 +
        scores.team_contribution * 0.25
    )

    # Highlights and mistakes
    scores.highlights = _find_highlights(player_id, role, decisions, game_log, roles)
    scores.mistakes = _find_mistakes(player_id, role, decisions, game_log, roles)

    return scores


def _is_good_skill_use(action: str, choice, target, role: Role, game_log: dict, roles: dict[int, Role]) -> bool:
    """Heuristic check for good skill usage."""
    if target is not None:
        target_role = get_role_of(target, roles)
        if target_role is None:
            return False
        if action == "witch_act" and choice == "poison":
            return target_role.team is Team.WEREWOLVES
        if action == "witch_act" and choice == "save":
            return target_role.team is not Team.WEREWOLVES
        if action == "hunter_shoot":
            return target_role.team is Team.WEREWOLVES
        if action == "guard_protect":
            return target_role.team is not Team.WEREWOLVES
        if action == "seer_check":
            return True  # Any check is informative
        if action == "werewolf_kill":
            return target_role.team is not Team.WEREWOLVES
    return True


def _find_highlights(player_id: int, role: Role, decisions: list[dict], game_log: dict, roles: dict[int, Role]) -> list[str]:
    highlights = []
    for d in decisions:
        # Highlight: correct vote against a wolf (confidence threshold removed)
        if d.get("source") == "llm":
            action = d.get("action_type", "")
            target = d.get("selected_target")
            if action in VOTE_ACTION_TYPES and target is not None:
                target_role = get_role_of(target, roles)
                if target_role and target_role.team is Team.WEREWOLVES and role.team is not Team.WEREWOLVES:
                    highlights.append(f"高置信度({d['confidence']:.0%})投票放逐狼人 P{target}")
            if action == "seer_check" and target is not None:
                highlights.append(f"查验了 P{target}，获得关键信息")
    if not highlights:
        highlights.append("完成了本局游戏")
    return highlights[:3]


def _find_mistakes(player_id: int, role: Role, decisions: list[dict], game_log: dict, roles: dict[int, Role]) -> list[str]:
    mistakes = []
    for d in decisions:
        source = d.get("source", "")
        if source == "fallback":
            mistakes.append(f"{d.get('action_type', 'unknown')} 使用了回退动作")
        if source == "policy_adjusted":
            mistakes.append(f"{d.get('action_type', 'unknown')} 被策略修正")
        # low-confidence mistake removed -- confidence is LLM self-report, not a quality signal
        # Check if poisoned a villager
        if d.get("action_type") == "witch_act" and d.get("selected_choice") == "poison":
            target = d.get("selected_target")
            if target is not None:
                target_role = get_role_of(target, roles)
                if target_role and target_role.team is not Team.WEREWOLVES:
                    mistakes.append(f"毒杀了 P{target} ({target_role.value})——毒错好人")
        # Check if hunter shot wrong
        if d.get("action_type") == "hunter_shoot":
            target = d.get("selected_target")
            if target is not None:
                target_role = get_role_of(target, roles)
                if target_role and target_role.team is not Team.WEREWOLVES:
                    mistakes.append(f"开枪带走了 P{target} ({target_role.value})——带错好人")
    return mistakes[:3]


def _detect_global_mistakes(scores: dict[int, AgentScores], game_log: dict) -> list[str]:
    mistakes = []
    for pid, s in scores.items():
        for m in s.mistakes:
            mistakes.append(f"P{pid} ({s.role}): {m}")
    return mistakes[:10]


def _detect_turning_points(game_log: dict, agent_decisions: dict[int, list[dict]]) -> list[str]:
    points = []
    # Find first death
    for pid, decisions in agent_decisions.items():
        for d in decisions:
            if d.get("action_type") == "werewolf_kill" and d.get("selected_target") is not None:
                points.append(f"狼人首刀 P{d['selected_target']}")
                break
        if points:
            break
    # Find witch poison on wrong target
    for pid, decisions in agent_decisions.items():
        for d in decisions:
            if d.get("action_type") == "witch_act" and d.get("selected_choice") == "poison":
                target = d.get("selected_target")
                points.append(f"女巫 P{pid} 使用毒药毒杀 P{target}")
                break
    # Find seer reveal
    for pid, decisions in agent_decisions.items():
        for d in decisions:
            if d.get("action_type") in {"sheriff_speak", "speak"} and "seer_claim" in d.get("selected_skills", []):
                points.append(f"预言家 P{pid} 跳身份公布查验链")
                break
    return points[:5]


def _generate_recommendations(review: GameReview) -> list[str]:
    recs = []
    for pid, s in review.agent_scores.items():
        if s.speech_quality < 4.0:
            recs.append(f"P{pid} ({s.role}) 发言质量偏低，建议增强 Prompt 中的发言指导。")
        if s.vote_accuracy < 4.0:
            recs.append(f"P{pid} ({s.role}) 投票准确率低，建议增强票型分析技能。")
        if s.skill_accuracy < 4.0:
            recs.append(f"P{pid} ({s.role}) 技能使用质量低，建议增强技能决策提示。")
    if not recs:
        recs.append("整体表现良好，可继续优化角色差异化和强推理。")
    return recs[:8]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def log_entries(game_log) -> list[dict]:
    """Normalize game_log to a list of dict entries.

    Handles:
    - ``list[dict]`` -- raw event list (e.g. from jsonl)
    - ``{"entries": [...]}`` -- GameLogger dict export
    - ``{"events": [...]}`` -- UI backend format
    - ``GameLogger`` object with ``.entries`` attribute
    """
    if isinstance(game_log, list):
        return game_log
    if isinstance(game_log, dict):
        if "entries" in game_log:
            entries = game_log["entries"]
        elif "events" in game_log:
            entries = game_log["events"]
        else:
            entries = []
        return [e if isinstance(e, dict) else e.to_dict() if hasattr(e, "to_dict") else {} for e in entries]
    if hasattr(game_log, "entries"):
        return [e.to_dict() if hasattr(e, "to_dict") else e for e in game_log.entries]
    return []


def did_survive(player_id: int, game_log) -> bool:
    """Check if player survived to the end (no death event targeting them)."""
    for entry in log_entries(game_log):
        if entry.get("event_type") == "death" and entry.get("target") == player_id:
            return False
    return True


def get_role_of(player_id: int, roles: dict[int, Role]) -> Role | None:
    """Return the known role of a player from the roles mapping."""
    return roles.get(player_id)