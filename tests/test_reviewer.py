"""Tests for agent.evolution.reviewer — post-game decision review and counterfactuals."""
from __future__ import annotations

from agent.learning.review.reviewer import (
    Counterfactual,
    DecisionReview,
    GameReviewer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision_review(**overrides) -> DecisionReview:
    defaults = dict(
        id="dr-001",
        game_id="g1",
        decision_id="d1",
        player_seat=1,
        day=2,
        phase="night",
        action_type="werewolf_kill",
        quality="good",
        reason="Killed the seer",
        alternative_action=None,
        created_at="2026-01-01T00:00:00+08:00",
    )
    defaults.update(overrides)
    return DecisionReview(**defaults)


def _make_counterfactual(**overrides) -> Counterfactual:
    defaults = dict(
        id="cf-001",
        game_id="g1",
        decision_id="d1",
        what_if="If wolves had killed a different player",
        likely_outcome="The seer would have survived",
        confidence=0.7,
        created_at="2026-01-01T00:00:00+08:00",
    )
    defaults.update(overrides)
    return Counterfactual(**defaults)


# ---------------------------------------------------------------------------
# DecisionReview.to_dict() round-trip
# ---------------------------------------------------------------------------


def test_decision_review_to_dict_round_trip():
    review = _make_decision_review()
    d = review.to_dict()

    assert d["id"] == "dr-001"
    assert d["game_id"] == "g1"
    assert d["decision_id"] == "d1"
    assert d["player_seat"] == 1
    assert d["day"] == 2
    assert d["phase"] == "night"
    assert d["action_type"] == "werewolf_kill"
    assert d["quality"] == "good"
    assert d["reason"] == "Killed the seer"
    assert d["alternative_action"] is None
    assert d["created_at"] == "2026-01-01T00:00:00+08:00"

    expected_keys = {
        "id", "game_id", "decision_id", "player_seat", "day", "phase",
        "action_type", "quality", "reason", "alternative_action", "created_at",
    }
    assert set(d.keys()) == expected_keys


def test_decision_review_to_dict_with_alternative():
    review = _make_decision_review(alternative_action="Target a god instead")
    d = review.to_dict()
    assert d["alternative_action"] == "Target a god instead"


# ---------------------------------------------------------------------------
# Counterfactual.to_dict() round-trip
# ---------------------------------------------------------------------------


def test_counterfactual_to_dict_round_trip():
    cf = _make_counterfactual()
    d = cf.to_dict()

    assert d["id"] == "cf-001"
    assert d["game_id"] == "g1"
    assert d["decision_id"] == "d1"
    assert d["what_if"] == "If wolves had killed a different player"
    assert d["likely_outcome"] == "The seer would have survived"
    assert d["confidence"] == 0.7
    assert d["created_at"] == "2026-01-01T00:00:00+08:00"

    expected_keys = {
        "id", "game_id", "decision_id", "what_if",
        "likely_outcome", "confidence", "created_at",
    }
    assert set(d.keys()) == expected_keys


def test_counterfactual_to_dict_rounds_confidence():
    cf = _make_counterfactual(confidence=0.6666666)
    d = cf.to_dict()
    assert d["confidence"] == 0.667


# ---------------------------------------------------------------------------
# _is_turning_point — various decision types
# ---------------------------------------------------------------------------


def test_is_turning_point_werewolf_kill_god():
    reviewer = GameReviewer()
    decision = {
        "action_type": "werewolf_kill",
        "player_id": 2,
        "selected_target": 1,
    }
    player_roles = {1: "seer", 2: "werewolf"}

    assert reviewer._is_turning_point(decision, [], player_roles) is True


def test_is_turning_point_werewolf_kill_villager_not_tp():
    reviewer = GameReviewer()
    decision = {
        "action_type": "werewolf_kill",
        "player_id": 2,
        "selected_target": 3,
    }
    player_roles = {2: "werewolf", 3: "villager"}

    assert reviewer._is_turning_point(decision, [], player_roles) is False


def test_is_turning_point_witch_act():
    reviewer = GameReviewer()
    decision = {
        "action_type": "witch_act",
        "player_id": 3,
        "selected_target": 1,
        "selected_choice": "save",
    }
    player_roles = {1: "seer", 3: "witch"}

    # Witch save or poison is always a turning point
    assert reviewer._is_turning_point(decision, [], player_roles) is True


def test_is_turning_point_seer_check_finds_wolf():
    reviewer = GameReviewer()
    decision = {
        "action_type": "seer_check",
        "player_id": 1,
        "selected_target": 2,
    }
    player_roles = {1: "seer", 2: "werewolf"}

    assert reviewer._is_turning_point(decision, [], player_roles) is True


def test_is_turning_point_seer_check_villager_not_tp():
    reviewer = GameReviewer()
    decision = {
        "action_type": "seer_check",
        "player_id": 1,
        "selected_target": 3,
    }
    player_roles = {1: "seer", 3: "villager"}

    assert reviewer._is_turning_point(decision, [], player_roles) is False


def test_is_turning_point_hunter_shoot():
    reviewer = GameReviewer()
    decision = {
        "action_type": "hunter_shoot",
        "player_id": 4,
        "selected_target": 2,
    }
    player_roles = {2: "werewolf", 4: "hunter"}

    assert reviewer._is_turning_point(decision, [], player_roles) is True


def test_is_turning_point_white_wolf_explode():
    reviewer = GameReviewer()
    decision = {
        "action_type": "white_wolf_explode",
        "player_id": 5,
    }
    player_roles = {5: "white_wolf_king"}

    assert reviewer._is_turning_point(decision, [], player_roles) is True


def test_is_turning_point_speech_not_tp():
    reviewer = GameReviewer()
    decision = {
        "action_type": "speak",
        "player_id": 1,
    }
    player_roles = {1: "seer"}

    assert reviewer._is_turning_point(decision, [], player_roles) is False


def test_is_turning_point_exile_vote_with_death():
    """Exile vote that removed a god/wolf is a turning point."""
    reviewer = GameReviewer()
    decision = {
        "action_type": "exile_vote",
        "player_id": 1,
        "selected_target": 2,
        "day": 2,
    }
    events = [
        {
            "event_type": "death",
            "target": 2,
            "day": 2,
            "payload": {"cause": "exile"},
        },
    ]
    player_roles = {1: "villager", 2: "werewolf"}

    assert reviewer._is_turning_point(decision, events, player_roles) is True


def test_is_turning_point_exile_vote_no_death():
    """Exile vote without matching death event is not a turning point."""
    reviewer = GameReviewer()
    decision = {
        "action_type": "exile_vote",
        "player_id": 1,
        "selected_target": 2,
        "day": 2,
    }
    player_roles = {1: "villager", 2: "werewolf"}

    assert reviewer._is_turning_point(decision, [], player_roles) is False


# ---------------------------------------------------------------------------
# review_game — produces reviews and counterfactuals
# ---------------------------------------------------------------------------


def test_review_game_identifies_turning_points():
    reviewer = GameReviewer()

    events = []
    decisions = [
        # Turning point: werewolf kills seer
        {
            "decision_id": "d1",
            "action_type": "werewolf_kill",
            "player_id": 2,
            "selected_target": 1,
            "day": 1,
            "phase": "night",
        },
        # Not a turning point: speech
        {
            "decision_id": "d2",
            "action_type": "speak",
            "player_id": 1,
            "day": 1,
            "phase": "day",
        },
        # Turning point: witch save
        {
            "decision_id": "d3",
            "action_type": "witch_act",
            "player_id": 3,
            "selected_target": 1,
            "selected_choice": "save",
            "day": 2,
            "phase": "night",
        },
    ]
    player_roles = {1: "seer", 2: "werewolf", 3: "witch"}

    # Mock evaluation
    class MockEval:
        players = []

    reviews, counterfactuals = reviewer.review_game(
        "g1",
        events=events,
        decisions=decisions,
        evaluation=MockEval(),
        player_roles=player_roles,
        winner="villagers",
    )

    # Two turning points: werewolf_kill (god target) and witch_act
    assert len(reviews) == 2
    # Both should have counterfactuals (werewolf_kill and witch save)
    assert len(counterfactuals) >= 1

    # Verify werewolf kill review
    kill_review = next(r for r in reviews if r.action_type == "werewolf_kill")
    assert kill_review.quality == "good"
    assert kill_review.player_seat == 2

    # Verify witch save review
    witch_review = next(r for r in reviews if r.action_type == "witch_act")
    assert witch_review.quality == "good"


def test_review_game_witch_poison_good_player():
    reviewer = GameReviewer()

    decisions = [
        {
            "decision_id": "d1",
            "action_type": "witch_act",
            "player_id": 3,
            "selected_target": 1,
            "selected_choice": "poison",
            "day": 2,
            "phase": "night",
        },
    ]
    player_roles = {1: "seer", 3: "witch"}

    class MockEval:
        players = []

    reviews, counterfactuals = reviewer.review_game(
        "g1",
        events=[],
        decisions=decisions,
        evaluation=MockEval(),
        player_roles=player_roles,
        winner="werewolves",
    )

    assert len(reviews) == 1
    assert reviews[0].quality == "bad"
    assert "poisoned good player" in reviews[0].reason

    # Should generate counterfactual for bad poison
    assert len(counterfactuals) == 1
    assert "withheld poison" in counterfactuals[0].what_if


def test_review_game_hunter_shoot_wolf():
    reviewer = GameReviewer()

    decisions = [
        {
            "decision_id": "d1",
            "action_type": "hunter_shoot",
            "player_id": 4,
            "selected_target": 2,
            "day": 3,
            "phase": "day",
        },
    ]
    player_roles = {2: "werewolf", 4: "hunter"}

    class MockEval:
        players = []

    reviews, counterfactuals = reviewer.review_game(
        "g1",
        events=[],
        decisions=decisions,
        evaluation=MockEval(),
        player_roles=player_roles,
        winner="villagers",
    )

    assert len(reviews) == 1
    assert reviews[0].quality == "good"
    assert "shot wolf" in reviews[0].reason


def test_review_game_no_turning_points():
    reviewer = GameReviewer()

    decisions = [
        {
            "decision_id": "d1",
            "action_type": "speak",
            "player_id": 1,
            "day": 1,
            "phase": "day",
        },
    ]
    player_roles = {1: "villager"}

    class MockEval:
        players = []

    reviews, counterfactuals = reviewer.review_game(
        "g1",
        events=[],
        decisions=decisions,
        evaluation=MockEval(),
        player_roles=player_roles,
        winner="villagers",
    )

    assert len(reviews) == 0
    assert len(counterfactuals) == 0


def test_review_game_evaluation_none():
    """review_game works even with evaluation=None."""
    reviewer = GameReviewer()

    decisions = [
        {
            "decision_id": "d1",
            "action_type": "hunter_shoot",
            "player_id": 4,
            "selected_target": 2,
            "day": 3,
            "phase": "day",
        },
    ]
    player_roles = {2: "werewolf", 4: "hunter"}

    reviews, counterfactuals = reviewer.review_game(
        "g1",
        events=[],
        decisions=decisions,
        evaluation=None,
        player_roles=player_roles,
        winner="villagers",
    )

    assert len(reviews) == 1
