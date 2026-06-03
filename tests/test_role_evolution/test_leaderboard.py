"""Tests for role evolution leaderboard: aggregation, CI, recommendations."""

import pytest

from agent.learning.evolution.leaderboard import (
    aggregate_role_leaderboard,
    compute_recommendation,
    wilson_ci,
    target_side_for_role,
)
from agent.learning.evolution.models import RoleLeaderboardEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _metrics(role: str, *, win_rate: float = 0.5, **overrides) -> dict:
    """Build a per-role metrics dict with sane defaults."""
    base = {
        "win_rate": win_rate,
        "role_weighted_score": 0.7,
        "speech_score": 0.7,
        "vote_score": 0.7,
        "skill_score": 0.7,
        "information_score": 0.7,
        "cooperation_score": 0.7,
        "fallback_rate": 0.05,
        "bad_case_rate": 0.02,
    }
    base.update(overrides)
    return {role: base}


def _side_metrics(role: str, win_rate: float = 0.5) -> dict:
    """Build side-level metrics for the given role's faction."""
    side = target_side_for_role(role)
    return {side: {"win_rate": win_rate}}


def _make_battle_summary(
    role: str,
    baseline_metrics: dict,
    candidate_metrics: dict,
    games: int = 15,
) -> dict:
    """Create a battle summary dict for aggregate_role_leaderboard."""
    return {
        "baseline_config": {
            "role_versions": {role: "base_hash"},
        },
        "candidate_config": {
            "role_versions": {role: "cand_hash"},
        },
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
        "games_played": games,
        "seeds": list(range(games)),
    }


def _make_entry(**kwargs) -> RoleLeaderboardEntry:
    """Create a RoleLeaderboardEntry with sensible defaults."""
    defaults = {
        "hash": "test_hash",
        "role": "seer",
        "battle_record": "W:10 L:5",
        "recommendation": "",
        "is_baseline": False,
        "total_games": 15,
        "target_role_role_weighted_score": 0.7,
        "target_role_speech_score": 0.7,
        "target_role_vote_score": 0.7,
        "target_role_skill_score": 0.7,
        "target_role_information_score": 0.7,
        "target_role_cooperation_score": 0.7,
        "target_role_fallback_rate": 0.05,
        "target_role_bad_case_rate": 0.02,
        "target_side_win_rate": 0.5,
        "target_side_win_rate_ci": (0.3, 0.7),
    }
    defaults.update(kwargs)
    return RoleLeaderboardEntry(**defaults)


# ---------------------------------------------------------------------------
# 1. test_aggregate_filters_by_target_role
# ---------------------------------------------------------------------------


def test_aggregate_filters_by_target_role():
    """Only the target role's metrics are aggregated; other roles ignored."""
    role = "seer"
    # Baseline side wins (seer -> villagers)
    baseline = {}
    baseline.update(_metrics("seer", win_rate=0.6, role_weighted_score=0.8))
    baseline.update(_side_metrics("seer", win_rate=0.6))
    baseline.update(_metrics("werewolf", win_rate=0.4, role_weighted_score=0.3))
    baseline.update(_side_metrics("werewolf", win_rate=0.4))

    # Candidate side loses
    candidate = {}
    candidate.update(_metrics("seer", win_rate=0.4, role_weighted_score=0.6))
    candidate.update(_side_metrics("seer", win_rate=0.4))
    candidate.update(_metrics("werewolf", win_rate=0.6, role_weighted_score=0.9))
    candidate.update(_side_metrics("werewolf", win_rate=0.6))

    summary = _make_battle_summary(role, baseline, candidate, games=15)
    entries = aggregate_role_leaderboard(role, [summary])

    assert len(entries) == 2
    # Verify seer metrics were used (not werewolf)
    base_entry = next(e for e in entries if e.is_baseline)
    assert base_entry.target_role_role_weighted_score == pytest.approx(0.8)
    # The werewolf role_weighted_score of 0.3 should NOT appear in seer entries
    assert base_entry.target_role_role_weighted_score != 0.3


# ---------------------------------------------------------------------------
# 2. test_target_side_win_rate_werewolf
# ---------------------------------------------------------------------------


def test_target_side_win_rate_werewolf():
    """For werewolf role, target_side_win_rate uses werewolves side win rate."""
    role = "werewolf"
    baseline = {}
    baseline.update(_metrics("werewolf", win_rate=0.7, role_weighted_score=0.8))
    baseline.update(_side_metrics("werewolf", win_rate=0.7))

    candidate = {}
    candidate.update(_metrics("werewolf", win_rate=0.5, role_weighted_score=0.6))
    candidate.update(_side_metrics("werewolf", win_rate=0.5))

    summary = _make_battle_summary(role, baseline, candidate, games=20)
    entries = aggregate_role_leaderboard(role, [summary])

    base_entry = next(e for e in entries if e.is_baseline)
    cand_entry = next(e for e in entries if not e.is_baseline)

    assert base_entry.target_side_win_rate == pytest.approx(0.7)
    assert cand_entry.target_side_win_rate == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 3. test_target_side_win_rate_seer
# ---------------------------------------------------------------------------


def test_target_side_win_rate_seer():
    """For seer role, target_side_win_rate uses villager side win rate."""
    role = "seer"
    baseline = {}
    baseline.update(_metrics("seer", win_rate=0.65))
    baseline.update(_side_metrics("seer", win_rate=0.65))

    candidate = {}
    candidate.update(_metrics("seer", win_rate=0.55))
    candidate.update(_side_metrics("seer", win_rate=0.55))

    summary = _make_battle_summary(role, baseline, candidate, games=20)
    entries = aggregate_role_leaderboard(role, [summary])

    base_entry = next(e for e in entries if e.is_baseline)
    # Seer is a villager role -> side should be "villagers"
    assert target_side_for_role("seer") == "villagers"
    assert base_entry.target_side_win_rate == pytest.approx(0.65)


# ---------------------------------------------------------------------------
# 4. test_wilson_ci
# ---------------------------------------------------------------------------


def test_wilson_ci():
    """Wilson CI for 8/10 successes should give ~0.49-0.94 interval."""
    lower, upper = wilson_ci(8, 10)
    assert 0.45 <= lower <= 0.55
    assert 0.90 <= upper <= 0.98


def test_wilson_ci_zero_total():
    """Wilson CI with 0 total returns (0, 0)."""
    assert wilson_ci(0, 0) == (0.0, 0.0)


def test_wilson_ci_perfect():
    """Wilson CI with perfect score covers near 1.0."""
    lower, upper = wilson_ci(100, 100)
    assert lower > 0.90
    assert upper == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 5. test_insufficient_data_marked
# ---------------------------------------------------------------------------


def test_insufficient_data_marked():
    """battle_games < 10 sets data_sufficient=False and recommendation='caution'."""
    role = "seer"
    baseline = {}
    baseline.update(_metrics("seer", win_rate=0.6))
    baseline.update(_side_metrics("seer", win_rate=0.6))

    candidate = {}
    candidate.update(_metrics("seer", win_rate=0.7))
    candidate.update(_side_metrics("seer", win_rate=0.7))

    summary = _make_battle_summary(role, baseline, candidate, games=5)
    entries = aggregate_role_leaderboard(role, [summary])

    cand_entry = next(e for e in entries if not e.is_baseline)
    assert cand_entry.data_sufficient is False
    assert cand_entry.recommendation == "caution"


# ---------------------------------------------------------------------------
# 6. test_recommendation_promote
# ---------------------------------------------------------------------------


def test_recommendation_promote():
    """All metrics at or above baseline -> 'promote'."""
    baseline = _make_entry(
        hash="base",
        is_baseline=True,
        target_role_role_weighted_score=0.7,
        target_side_win_rate=0.5,
        target_role_fallback_rate=0.05,
        target_role_bad_case_rate=0.02,
        target_role_speech_score=0.7,
        target_role_vote_score=0.7,
        target_role_skill_score=0.7,
        target_role_information_score=0.7,
        target_role_cooperation_score=0.7,
    )
    candidate = _make_entry(
        hash="cand",
        total_games=15,
        target_role_role_weighted_score=0.75,
        target_side_win_rate=0.55,
        target_role_fallback_rate=0.04,
        target_role_bad_case_rate=0.01,
        target_role_speech_score=0.75,
        target_role_vote_score=0.75,
        target_role_skill_score=0.75,
        target_role_information_score=0.75,
        target_role_cooperation_score=0.75,
    )
    assert compute_recommendation(candidate, baseline) == "promote"


# ---------------------------------------------------------------------------
# 7. test_recommendation_reject_score_drop
# ---------------------------------------------------------------------------


def test_recommendation_reject_score_drop():
    """target_role_role_weighted_score below baseline -> 'reject'."""
    baseline = _make_entry(
        hash="base",
        is_baseline=True,
        target_role_role_weighted_score=0.8,
        target_side_win_rate=0.5,
        target_role_fallback_rate=0.05,
        target_role_bad_case_rate=0.02,
        target_role_speech_score=0.7,
        target_role_vote_score=0.7,
        target_role_skill_score=0.7,
        target_role_information_score=0.7,
        target_role_cooperation_score=0.7,
    )
    candidate = _make_entry(
        hash="cand",
        total_games=15,
        target_role_role_weighted_score=0.6,  # below baseline 0.8
        target_side_win_rate=0.5,
        target_role_fallback_rate=0.05,
        target_role_bad_case_rate=0.02,
        target_role_speech_score=0.7,
        target_role_vote_score=0.7,
        target_role_skill_score=0.7,
        target_role_information_score=0.7,
        target_role_cooperation_score=0.7,
    )
    assert compute_recommendation(candidate, baseline) == "reject"


# ---------------------------------------------------------------------------
# 8. test_recommendation_reject_win_rate_drop
# ---------------------------------------------------------------------------


def test_recommendation_reject_win_rate_drop():
    """target_side_win_rate drops > 10% from baseline -> 'reject'."""
    baseline = _make_entry(
        hash="base",
        is_baseline=True,
        target_role_role_weighted_score=0.7,
        target_side_win_rate=0.60,
        target_role_fallback_rate=0.05,
        target_role_bad_case_rate=0.02,
        target_role_speech_score=0.7,
        target_role_vote_score=0.7,
        target_role_skill_score=0.7,
        target_role_information_score=0.7,
        target_role_cooperation_score=0.7,
    )
    candidate = _make_entry(
        hash="cand",
        total_games=15,
        target_role_role_weighted_score=0.7,
        target_side_win_rate=0.45,  # drop of 15% > 10%
        target_role_fallback_rate=0.05,
        target_role_bad_case_rate=0.02,
        target_role_speech_score=0.7,
        target_role_vote_score=0.7,
        target_role_skill_score=0.7,
        target_role_information_score=0.7,
        target_role_cooperation_score=0.7,
    )
    assert compute_recommendation(candidate, baseline) == "reject"


# ---------------------------------------------------------------------------
# 9. test_recommendation_caution_slight_regression
# ---------------------------------------------------------------------------


def test_recommendation_caution_slight_regression():
    """Some metrics slightly below baseline -> 'caution'."""
    baseline = _make_entry(
        hash="base",
        is_baseline=True,
        target_role_role_weighted_score=0.7,
        target_side_win_rate=0.5,
        target_role_fallback_rate=0.05,
        target_role_bad_case_rate=0.02,
        target_role_speech_score=0.7,
        target_role_vote_score=0.7,
        target_role_skill_score=0.7,
        target_role_information_score=0.7,
        target_role_cooperation_score=0.7,
    )
    candidate = _make_entry(
        hash="cand",
        total_games=15,
        target_role_role_weighted_score=0.7,  # equal, not below
        target_side_win_rate=0.5,
        target_role_fallback_rate=0.05,
        target_role_bad_case_rate=0.02,
        target_role_speech_score=0.65,  # slightly below
        target_role_vote_score=0.7,
        target_role_skill_score=0.7,
        target_role_information_score=0.7,
        target_role_cooperation_score=0.7,
    )
    assert compute_recommendation(candidate, baseline) == "caution"


# ---------------------------------------------------------------------------
# 10. test_target_side_mapping
# ---------------------------------------------------------------------------


def test_target_side_mapping():
    """Verify role -> faction side mapping."""
    assert target_side_for_role("werewolf") == "werewolves"
    assert target_side_for_role("white_wolf_king") == "werewolves"
    assert target_side_for_role("seer") == "villagers"
    assert target_side_for_role("witch") == "villagers"
    assert target_side_for_role("hunter") == "villagers"
    assert target_side_for_role("guard") == "villagers"
    assert target_side_for_role("villager") == "villagers"
