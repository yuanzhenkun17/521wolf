"""Tests for leaderboard metric extensions."""
from agent.learning.leaderboard import aggregate_summaries, LeaderboardEntry


def _make_summary(**overrides):
    base = {
        "run_id": "test_run",
        "games": 10,
        "werewolf_wins": 5,
        "villager_wins": 5,
        "error_count": 0,
        "avg_days": 4.0,
        "avg_decision_score": 6.0,
        "avg_speech_score": 7.0,
        "avg_vote_score": 5.5,
        "avg_skill_score": 6.5,
        "avg_confidence": 0.8,
        "confidence_calibration_error": 0.0,
        "confidence_calibration_count": 2,
        "confidence_buckets": {
            "0.8-1.0": {
                "count": 2,
                "correct": 1,
                "confidence_sum": 1.7,
                "avg_confidence": 0.85,
                "accuracy": 0.5,
                "error": 0.35,
            },
        },
        "fallback_rate": 0.05,
        "vote_accuracy": 0.7,
        "skill_accuracy": 0.6,
        "policy_adjusted_rate": 0.02,
        "bad_case_count": 2.0,
        "turning_point_quality": 0.65,
        "information_score": 5.5,
        "cooperation_score": 6.0,
        "by_role": {
            "werewolf": {"wins": 5, "losses": 5},
        },
    }
    base.update(overrides)
    return base


def test_aggregate_bad_case_count():
    s = _make_summary()
    entry = aggregate_summaries([s])
    assert entry.bad_case_count == 2.0


def test_aggregate_turning_point_quality():
    s = _make_summary()
    entry = aggregate_summaries([s])
    assert abs(entry.turning_point_quality - 0.65) < 0.001


def test_aggregate_information_cooperation_weighted():
    s1 = _make_summary(games=10, information_score=4.0, cooperation_score=5.0)
    s2 = _make_summary(games=20, information_score=8.0, cooperation_score=7.0)
    entry = aggregate_summaries([s1, s2])
    # weighted: (4*10 + 8*20) / 30 = 200/30 = 6.667
    assert abs(entry.information_score - 6.667) < 0.01
    # weighted: (5*10 + 7*20) / 30 = 190/30 = 6.333
    assert abs(entry.cooperation_score - 6.333) < 0.01


def test_aggregate_by_role_merging():
    s1 = _make_summary(by_role={"werewolf": {"wins": 3, "losses": 2}})
    s2 = _make_summary(by_role={"werewolf": {"wins": 4, "losses": 1}, "seer": {"wins": 2, "losses": 0}})
    entry = aggregate_summaries([s1, s2])
    assert entry.by_role["werewolf"]["wins"] == 7
    assert entry.by_role["werewolf"]["losses"] == 3
    assert entry.by_role["seer"]["wins"] == 2


def test_to_dict_includes_new_fields():
    s = _make_summary()
    entry = aggregate_summaries([s])
    d = entry.to_dict()
    assert "bad_case_count" in d
    assert "turning_point_quality" in d
    assert "information_score" in d
    assert "cooperation_score" in d
    assert "by_role" in d
    assert "confidence_calibration_error" in d
    assert "confidence_calibration_count" in d
    assert "confidence_buckets" in d


def test_aggregate_confidence_calibration():
    entry = aggregate_summaries([_make_summary()])
    assert entry.confidence_calibration_count == 2
    assert abs(entry.confidence_calibration_error - 0.35) < 0.001
    assert entry.confidence_buckets["0.8-1.0"]["correct"] == 1
