"""Evaluation scoring metrics.

Implements the role_score formula and model/role-version aggregation
for benchmark leaderboards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Default scoring weights per spec
_DEFAULT_WEIGHTS = {
    "speech_score": 0.25,
    "vote_score": 0.25,
    "skill_score": 0.20,
    "logic_score": 0.20,
    "team_score": 0.10,
}

# Role categories for model leaderboard aggregation
_ROLE_CATEGORIES = {
    "werewolf": "wolf",
    "white_wolf_king": "wolf",
    "villager": "villager",
    "seer": "god",
    "witch": "god",
    "hunter": "god",
    "guard": "god",
}


@dataclass
class PlayerScore:
    """Scored evaluation for a single player in one game."""

    player_id: int
    role: str
    speech_score: float = 0.0
    vote_score: float = 0.0
    skill_score: float = 0.0
    logic_score: float = 0.0
    team_score: float = 0.0
    risk_penalty: float = 0.0
    role_score: float = 0.0
    skill_applicable: bool = True

    @property
    def role_category(self) -> str:
        return _ROLE_CATEGORIES.get(self.role, "other")


@dataclass
class GameScoreSummary:
    """Aggregated scores for one game."""

    game_id: str
    player_scores: list[PlayerScore] = field(default_factory=list)


@dataclass
class BatchScoreSummary:
    """Aggregated scores across a batch of games."""

    batch_id: str
    game_count: int = 0
    valid_game_count: int = 0
    avg_role_score: float = 0.0
    by_role_category: dict[str, float] = field(default_factory=dict)
    avg_speech_score: float = 0.0
    avg_vote_score: float = 0.0
    avg_skill_score: float = 0.0
    avg_logic_score: float = 0.0
    avg_team_score: float = 0.0
    avg_risk_penalty: float = 0.0
    strength_score: float = 0.0  # equal-weight average of role categories


def compute_role_score(
    *,
    speech_score: float,
    vote_score: float,
    skill_score: float,
    logic_score: float,
    team_score: float,
    risk_penalty: float = 0.0,
    skill_applicable: bool = True,
    weights: dict[str, float] | None = None,
) -> float:
    """Compute role_score = weighted_base_score - risk_penalty.

    When skill is not applicable, weights are renormalized.
    """
    w = dict(weights or _DEFAULT_WEIGHTS)

    if not skill_applicable:
        # Remove skill_score weight and renormalize
        skill_weight = w.pop("skill_score", 0.0)
        total_remaining = sum(w.values())
        if total_remaining > 0:
            w = {k: v / total_remaining for k, v in w.items()}
        skill_score = 0.0

    base = (
        w.get("speech_score", 0) * speech_score
        + w.get("vote_score", 0) * vote_score
        + w.get("skill_score", 0) * skill_score
        + w.get("logic_score", 0) * logic_score
        + w.get("team_score", 0) * team_score
    )
    return max(0.0, base - risk_penalty)


def aggregate_batch_scores(
    player_scores: list[PlayerScore],
    batch_id: str = "",
) -> BatchScoreSummary:
    """Aggregate player scores across a batch of games.

    Model leaderboard: equal-weight average across role categories.
    """
    if not player_scores:
        return BatchScoreSummary(batch_id=batch_id)

    # Aggregate by role category
    category_scores: dict[str, list[float]] = {}
    for ps in player_scores:
        cat = ps.role_category
        category_scores.setdefault(cat, []).append(ps.role_score)

    by_role_category: dict[str, float] = {}
    for cat, scores in category_scores.items():
        by_role_category[cat] = sum(scores) / len(scores) if scores else 0.0

    # Model strength = equal-weight average across categories
    strength_score = (
        sum(by_role_category.values()) / len(by_role_category) if by_role_category else 0.0
    )

    n = len(player_scores)
    return BatchScoreSummary(
        batch_id=batch_id,
        game_count=n,
        valid_game_count=n,
        avg_role_score=sum(ps.role_score for ps in player_scores) / n,
        by_role_category=by_role_category,
        avg_speech_score=sum(ps.speech_score for ps in player_scores) / n,
        avg_vote_score=sum(ps.vote_score for ps in player_scores) / n,
        avg_skill_score=sum(ps.skill_score for ps in player_scores) / n,
        avg_logic_score=sum(ps.logic_score for ps in player_scores) / n,
        avg_team_score=sum(ps.team_score for ps in player_scores) / n,
        avg_risk_penalty=sum(ps.risk_penalty for ps in player_scores) / n,
        strength_score=strength_score,
    )
