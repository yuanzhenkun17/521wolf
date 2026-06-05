"""Benchmark leaderboard computation.

Computes model leaderboard and role-version leaderboard from
evaluation batch results.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.common import beijing_now_iso

_log = logging.getLogger(__name__)


@dataclass
class LeaderboardEntry:
    """A single entry in a benchmark leaderboard."""

    id: str
    scope: str  # "model" | "role_version"
    subject_id: str  # model_id or "role:version_id"
    model_id: str = ""
    model_config_hash: str = ""
    target_role: str = ""
    target_version_id: str = ""
    comparison_group_id: str = ""
    evaluation_set_id: str = ""
    seed_set_id: str = ""
    ruleset_version: str = "werewolf_12p_v1"
    scoring_version: str = "scoring_v1"
    evaluator_config_hash: str = "rule_heuristic_v1"
    games_played: int = 0
    valid_game_rate: float = 0.0
    strength_score: float = 0.0
    avg_role_score: float = 0.0
    by_role_category_scores: dict[str, float] = field(default_factory=dict)
    avg_speech_score: float = 0.0
    avg_vote_score: float = 0.0
    avg_skill_score: float = 0.0
    avg_logic_score: float = 0.0
    avg_team_score: float = 0.0
    risk_penalty: float = 0.0
    rankable: bool = False
    data_sufficient: bool = False
    summary: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope,
            "subject_id": self.subject_id,
            "model_id": self.model_id,
            "target_role": self.target_role,
            "target_version_id": self.target_version_id,
            "comparison_group_id": self.comparison_group_id,
            "games_played": self.games_played,
            "strength_score": round(self.strength_score, 4),
            "avg_role_score": round(self.avg_role_score, 4),
            "by_role_category_scores": {
                k: round(v, 4) for k, v in self.by_role_category_scores.items()
            },
            "rankable": self.rankable,
            "data_sufficient": self.data_sufficient,
            "updated_at": self.updated_at,
        }


def compute_model_leaderboard_entry(
    *,
    batch_id: str,
    model_id: str,
    model_config_hash: str,
    evaluation_set_id: str,
    seed_set_id: str,
    score_summary: Any,
    rankable: bool,
    game_count: int,
) -> LeaderboardEntry:
    """Create a model leaderboard entry from a batch score summary."""
    data_sufficient = rankable and game_count >= 20

    return LeaderboardEntry(
        id=f"model_{model_id}_{batch_id}",
        scope="model",
        subject_id=model_id,
        model_id=model_id,
        model_config_hash=model_config_hash,
        evaluation_set_id=evaluation_set_id,
        seed_set_id=seed_set_id,
        games_played=game_count,
        valid_game_rate=1.0 if game_count > 0 else 0.0,
        strength_score=score_summary.strength_score if score_summary else 0.0,
        avg_role_score=score_summary.avg_role_score if score_summary else 0.0,
        by_role_category_scores=score_summary.by_role_category if score_summary else {},
        avg_speech_score=score_summary.avg_speech_score if score_summary else 0.0,
        avg_vote_score=score_summary.avg_vote_score if score_summary else 0.0,
        avg_skill_score=score_summary.avg_skill_score if score_summary else 0.0,
        avg_logic_score=score_summary.avg_logic_score if score_summary else 0.0,
        avg_team_score=score_summary.avg_team_score if score_summary else 0.0,
        risk_penalty=score_summary.avg_risk_penalty if score_summary else 0.0,
        rankable=rankable,
        data_sufficient=data_sufficient,
        updated_at=beijing_now_iso(),
    )


def compute_role_version_leaderboard_entry(
    *,
    batch_id: str,
    target_role: str,
    target_version_id: str,
    model_id: str,
    evaluation_set_id: str,
    seed_set_id: str,
    score_summary: Any,
    rankable: bool,
    game_count: int,
) -> LeaderboardEntry:
    """Create a role-version leaderboard entry from a batch score summary."""
    data_sufficient = rankable and game_count >= 20

    # For role-version leaderboard, the main score is the target role's score
    target_score = 0.0
    if score_summary and score_summary.by_role_category:
        # Find target role's category score
        from agent.evaluation.metrics import _ROLE_CATEGORIES
        target_cat = _ROLE_CATEGORIES.get(target_role, "other")
        target_score = score_summary.by_role_category.get(target_cat, 0.0)

    return LeaderboardEntry(
        id=f"role_{target_role}_{target_version_id}_{batch_id}",
        scope="role_version",
        subject_id=f"{target_role}:{target_version_id}",
        model_id=model_id,
        target_role=target_role,
        target_version_id=target_version_id,
        evaluation_set_id=evaluation_set_id,
        seed_set_id=seed_set_id,
        games_played=game_count,
        valid_game_rate=1.0 if game_count > 0 else 0.0,
        strength_score=target_score,
        avg_role_score=score_summary.avg_role_score if score_summary else 0.0,
        by_role_category_scores=score_summary.by_role_category if score_summary else {},
        avg_speech_score=score_summary.avg_speech_score if score_summary else 0.0,
        avg_vote_score=score_summary.avg_vote_score if score_summary else 0.0,
        avg_skill_score=score_summary.avg_skill_score if score_summary else 0.0,
        avg_logic_score=score_summary.avg_logic_score if score_summary else 0.0,
        avg_team_score=score_summary.avg_team_score if score_summary else 0.0,
        risk_penalty=score_summary.avg_risk_penalty if score_summary else 0.0,
        rankable=rankable,
        data_sufficient=data_sufficient,
        updated_at=beijing_now_iso(),
    )


def persist_leaderboard_entry(conn: Any, entry: LeaderboardEntry) -> None:
    """Persist a leaderboard entry to the benchmark_leaderboard table."""
    conn.execute(
        "INSERT OR REPLACE INTO benchmark_leaderboard "
        "(id, scope, subject_id, model_id, model_config_hash, "
        "target_role, target_version_id, comparison_group_id, "
        "evaluation_set_id, seed_set_id, ruleset_version, scoring_version, "
        "evaluator_config_hash, games_played, valid_game_rate, "
        "strength_score, avg_role_score, by_role_category_scores, "
        "avg_speech_score, avg_vote_score, avg_skill_score, "
        "avg_logic_score, avg_team_score, risk_penalty, "
        "rankable, data_sufficient, summary, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            entry.id,
            entry.scope,
            entry.subject_id,
            entry.model_id,
            entry.model_config_hash,
            entry.target_role,
            entry.target_version_id,
            entry.comparison_group_id,
            entry.evaluation_set_id,
            entry.seed_set_id,
            entry.ruleset_version,
            entry.scoring_version,
            entry.evaluator_config_hash,
            entry.games_played,
            entry.valid_game_rate,
            entry.strength_score,
            entry.avg_role_score,
            json.dumps(entry.by_role_category_scores, ensure_ascii=False),
            entry.avg_speech_score,
            entry.avg_vote_score,
            entry.avg_skill_score,
            entry.avg_logic_score,
            entry.avg_team_score,
            entry.risk_penalty,
            1 if entry.rankable else 0,
            1 if entry.data_sufficient else 0,
            entry.summary,
            entry.updated_at,
        ),
    )
    conn.commit()
