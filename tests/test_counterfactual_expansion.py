"""Tests for expanded counterfactual coverage."""
from agent.evaluation.review_enhanced import (
    _generate_counterfactuals, _collect_mistakes,
    DecisionMistake, MISTAKE_WRONG_VOTE, MISTAKE_KILLED_TEAMMATE,
    MISTAKE_POISONED_GOOD, MISTAKE_SHOT_GOOD, MISTAKE_IGNORED_SEER,
)
from engine.models import Role


def test_counterfactual_wrong_vote():
    mistakes = [DecisionMistake(
        player_id=1, role="villager", day=2, phase="day",
        action_type="exile_vote", mistake_type=MISTAKE_WRONG_VOTE,
        description="投票放逐了好人", severity="medium",
    )]
    cfs = _generate_counterfactuals(mistakes, {}, {})
    assert len(cfs) >= 1
    assert "投票" in cfs[0].fact


def test_counterfactual_killed_teammate():
    mistakes = [DecisionMistake(
        player_id=1, role="werewolf", day=1, phase="night",
        action_type="werewolf_kill", mistake_type=MISTAKE_KILLED_TEAMMATE,
        description="狼人P1 刀杀队友 P3", severity="high",
    )]
    cfs = _generate_counterfactuals(mistakes, {}, {})
    assert len(cfs) >= 1
    assert "队友" in cfs[0].fact


def test_counterfactual_ignored_seer():
    mistakes = [DecisionMistake(
        player_id=2, role="villager", day=3, phase="day",
        action_type="exile_vote", mistake_type=MISTAKE_IGNORED_SEER,
        description="P2 投票放逐了预言家查验为好人的 P5", severity="medium",
    )]
    cfs = _generate_counterfactuals(mistakes, {}, {})
    assert len(cfs) >= 1
    assert "预言家" in cfs[0].fact


def test_at_least_five_mistake_types_covered():
    """Verify the counterfactual generator handles at least 5 mistake types."""
    covered = set()
    for mt in [MISTAKE_POISONED_GOOD, MISTAKE_SHOT_GOOD, MISTAKE_WRONG_VOTE,
               MISTAKE_KILLED_TEAMMATE, MISTAKE_IGNORED_SEER]:
        mistakes = [DecisionMistake(
            player_id=1, role="villager", day=1, phase="day",
            action_type="test", mistake_type=mt, description="test", severity="medium",
        )]
        cfs = _generate_counterfactuals(mistakes, {}, {})
        if cfs:
            covered.add(mt)
    assert len(covered) >= 5, f"Only covered {len(covered)} types: {covered}"
