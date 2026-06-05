"""Tests for enhanced summary fields."""
from pathlib import Path

from agent.learning.evolution.games import SelfPlayConfig, SelfPlayGameResult, SelfPlayResult


def test_game_result_to_dict_includes_counts():
    r = SelfPlayGameResult(
        game_id="g1", seed=1, winner="werewolves", days=4,
        player_roles={1: "werewolf"}, decision_count=10,
        fallback_count=0, policy_adjusted_count=0, avg_confidence=0.8,
        review_score=7.0, output_dir=Path("/tmp"),
        mistake_count=3, counterfactual_count=2, turning_point_count=1,
    )
    d = r.to_dict()
    assert d["mistake_count"] == 3
    assert d["counterfactual_count"] == 2
    assert d["turning_point_count"] == 1


def test_summary_includes_counts():
    config = SelfPlayConfig(games=1)
    r = SelfPlayResult(config=config, games=[
        SelfPlayGameResult(
            game_id="g1", seed=1, winner="werewolves", days=4,
            player_roles={1: "werewolf"}, decision_count=10,
            fallback_count=0, policy_adjusted_count=0, avg_confidence=0.8,
            review_score=7.0, output_dir=Path("/tmp"),
            mistake_count=3, counterfactual_count=2, turning_point_count=1,
        )
    ], run_id="test")
    s = r.summary
    assert s["mistake_count"] == 3
    assert s["counterfactual_count"] == 2
    assert s["turning_point_count"] == 1
