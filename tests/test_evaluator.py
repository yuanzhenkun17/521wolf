"""Tests for agent.evolution.evaluator — post-game multi-dimensional evaluation."""
from __future__ import annotations

from agent.learning.review.evaluator import (
    GameEvaluation,
    GameEvaluator,
    PlayerEvaluation,
    _clamp,
    _extract_mentioned_players,
    _get_seat,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_player_eval(**overrides) -> PlayerEvaluation:
    defaults = dict(
        id="pe-001",
        game_id="g1",
        player_seat=1,
        role="seer",
        speech_score=0.7,
        vote_score=0.6,
        skill_score=0.8,
        logic_score=0.65,
        team_score=0.55,
        risk_penalty=0.0,
        role_score=0.66,
        score_completeness=1.0,
        information_score=0.65,
        cooperation_score=0.55,
        overall_score=0.66,
        created_at="2026-01-01T00:00:00+08:00",
    )
    defaults.update(overrides)
    return PlayerEvaluation(**defaults)


# ---------------------------------------------------------------------------
# PlayerEvaluation.to_dict() round-trip
# ---------------------------------------------------------------------------


def test_player_evaluation_to_dict_round_trip():
    pe = _make_player_eval()
    d = pe.to_dict()

    assert d["id"] == "pe-001"
    assert d["game_id"] == "g1"
    assert d["player_seat"] == 1
    assert d["role"] == "seer"
    assert d["speech_score"] == 0.7
    assert d["vote_score"] == 0.6
    assert d["skill_score"] == 0.8
    assert d["logic_score"] == 0.65
    assert d["team_score"] == 0.55
    assert d["risk_penalty"] == 0.0
    assert d["role_score"] == 0.66
    assert d["information_score"] == 0.65
    assert d["cooperation_score"] == 0.55
    assert d["overall_score"] == 0.66
    assert d["created_at"] == "2026-01-01T00:00:00+08:00"

    expected_keys = {
        "id", "game_id", "player_seat", "role",
        "speech_score", "vote_score", "skill_score",
        "logic_score", "team_score", "risk_penalty", "role_score",
        "information_score", "cooperation_score", "overall_score",
        "created_at",
    }
    assert set(d.keys()) == expected_keys


def test_player_evaluation_to_dict_rounds_scores():
    pe = _make_player_eval(speech_score=0.6666666, vote_score=0.3333333)
    d = pe.to_dict()
    assert d["speech_score"] == 0.667
    assert d["vote_score"] == 0.333


# ---------------------------------------------------------------------------
# GameEvaluation.to_dict() round-trip
# ---------------------------------------------------------------------------


def test_game_evaluation_to_dict_round_trip():
    pe1 = _make_player_eval(id="pe1", player_seat=1, role="seer")
    pe2 = _make_player_eval(id="pe2", player_seat=2, role="werewolf")
    ge = GameEvaluation(game_id="g1", players=[pe1, pe2])

    d = ge.to_dict()

    assert d["game_id"] == "g1"
    assert len(d["players"]) == 2
    assert d["players"][0]["id"] == "pe1"
    assert d["players"][1]["id"] == "pe2"
    assert set(d.keys()) == {"game_id", "players"}


def test_game_evaluation_empty_players():
    ge = GameEvaluation(game_id="g1")
    d = ge.to_dict()
    assert d["players"] == []


# ---------------------------------------------------------------------------
# evaluate_game produces valid scores
# ---------------------------------------------------------------------------


def test_evaluate_game_produces_scores_in_range():
    evaluator = GameEvaluator()

    events = [
        {
            "event_type": "death",
            "day": 2,
            "target": 2,
            "payload": {"cause": "exile", "role": "werewolf"},
        },
    ]
    decisions = [
        {
            "action_type": "seer_check",
            "player_id": 1,
            "selected_target": 2,
            "day": 1,
            "phase": "night",
        },
        {
            "action_type": "exile_vote",
            "player_id": 1,
            "selected_target": 2,
            "day": 2,
            "phase": "day",
        },
        {
            "action_type": "werewolf_kill",
            "player_id": 2,
            "selected_target": 3,
            "day": 1,
            "phase": "night",
        },
        {
            "action_type": "exile_vote",
            "player_id": 2,
            "selected_target": 1,
            "day": 2,
            "phase": "day",
        },
    ]
    player_roles = {1: "seer", 2: "werewolf", 3: "villager"}

    evaluation = evaluator.evaluate_game(
        "g1",
        events=events,
        decisions=decisions,
        player_roles=player_roles,
        winner="villagers",
    )

    assert evaluation.game_id == "g1"
    assert len(evaluation.players) == 3

    for pe in evaluation.players:
        assert 0.0 <= pe.speech_score <= 1.0
        assert 0.0 <= pe.vote_score <= 1.0
        assert 0.0 <= pe.skill_score <= 1.0
        assert 0.0 <= pe.information_score <= 1.0
        assert 0.0 <= pe.cooperation_score <= 1.0
        assert 0.0 <= pe.overall_score <= 1.0


def test_evaluate_game_villager_has_baseline_skill():
    evaluator = GameEvaluator()
    events = []
    decisions = []
    player_roles = {1: "villager"}

    evaluation = evaluator.evaluate_game(
        "g1",
        events=events,
        decisions=decisions,
        player_roles=player_roles,
        winner="villagers",
    )

    pe = evaluation.players[0]
    # Villager skill score baseline is 0.5
    assert pe.skill_score == 0.5


def test_evaluate_game_winning_team_gets_coop_bonus():
    evaluator = GameEvaluator()
    events = []
    decisions = []
    player_roles = {1: "villager", 2: "werewolf"}

    evaluation = evaluator.evaluate_game(
        "g1",
        events=events,
        decisions=decisions,
        player_roles=player_roles,
        winner="villagers",
    )

    villager_eval = next(p for p in evaluation.players if p.role == "villager")
    wolf_eval = next(p for p in evaluation.players if p.role == "werewolf")

    # Villager won -> cooperation >= 0.6 (0.5 base + 0.1 win bonus)
    assert villager_eval.cooperation_score >= 0.6
    # Wolf lost -> cooperation stays at 0.5
    assert wolf_eval.cooperation_score == 0.5


# ---------------------------------------------------------------------------
# Dimension scoring — speech
# ---------------------------------------------------------------------------


def test_score_speech_base_no_decisions():
    evaluator = GameEvaluator()
    score = evaluator._score_speech(1, events=[], decisions=[])
    assert score == 0.5


def test_score_speech_bonus_for_mentioning_players():
    evaluator = GameEvaluator()
    decisions = [
        {
            "action_type": "speak",
            "player_id": 1,
            "public_text": "I suspect P2 and P3 are wolves, P4 seems fine",
            "day": 1,
        },
    ]
    score = evaluator._score_speech(1, events=[], decisions=decisions)
    # base 0.5 + 0.1 * min(3 mentions, 3) = 0.8
    assert score >= 0.7


def test_score_speech_penalty_for_short_text():
    evaluator = GameEvaluator()
    decisions = [
        {
            "action_type": "speak",
            "player_id": 1,
            "public_text": "hi",
            "day": 1,
        },
    ]
    score = evaluator._score_speech(1, events=[], decisions=decisions)
    # base 0.5 - 0.1 (short text) = 0.4
    assert score < 0.5


# ---------------------------------------------------------------------------
# Dimension scoring — vote
# ---------------------------------------------------------------------------


def test_score_vote_good_player_voting_wolf():
    evaluator = GameEvaluator()
    decisions = [
        {
            "action_type": "exile_vote",
            "player_id": 1,
            "selected_target": 2,
            "day": 2,
        },
    ]
    events = [
        {
            "event_type": "death",
            "target": 2,
            "payload": {"cause": "exile", "role": "werewolf"},
        },
    ]
    player_roles = {1: "villager", 2: "werewolf"}

    score = evaluator._score_vote(1, events, decisions, "villager", player_roles)
    # Good vote bonus: +0.1
    assert score >= 0.6


def test_score_vote_against_teammate_penalty():
    evaluator = GameEvaluator()
    decisions = [
        {
            "action_type": "exile_vote",
            "player_id": 1,
            "selected_target": 3,
            "day": 2,
        },
    ]
    player_roles = {1: "villager", 3: "seer"}

    score = evaluator._score_vote(1, [], decisions, "villager", player_roles)
    # Both are good team -> bad vote -> -0.15
    assert score <= 0.4


# ---------------------------------------------------------------------------
# Dimension scoring — skill
# ---------------------------------------------------------------------------


def test_score_skill_seer_correct_wolf_check():
    evaluator = GameEvaluator()
    decisions = [
        {
            "action_type": "seer_check",
            "player_id": 1,
            "selected_target": 2,
            "day": 1,
        },
    ]
    player_roles = {1: "seer", 2: "werewolf"}

    score = evaluator._score_skill(1, "seer", decisions, [], "villagers", player_roles)
    # base 0.5 + 0.2 (wolf check) + 0.1 (early day<=2) = 0.8
    assert score >= 0.7


def test_score_skill_witch_poison_teammate():
    evaluator = GameEvaluator()
    decisions = [
        {
            "action_type": "witch_act",
            "player_id": 3,
            "selected_target": 1,
            "selected_choice": "poison",
            "day": 2,
        },
    ]
    player_roles = {1: "seer", 3: "witch"}

    score = evaluator._score_skill(3, "witch", decisions, [], "villagers", player_roles)
    # base 0.5 - 0.2 (poisoned teammate) = 0.3
    assert score <= 0.4


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def test_clamp():
    assert _clamp(0.5) == 0.5
    assert _clamp(-1.0) == 0.0
    assert _clamp(2.0) == 1.0
    assert _clamp(0.0) == 0.0
    assert _clamp(1.0) == 1.0


def test_extract_mentioned_players():
    assert _extract_mentioned_players("I think P2 is suspicious") == {2}
    assert _extract_mentioned_players("P1 and P3 are wolves") == {1, 3}
    assert _extract_mentioned_players("p12 is fine") == {12}
    assert _extract_mentioned_players("no mentions here") == set()
    assert _extract_mentioned_players("") == set()


def test_get_seat_various_keys():
    assert _get_seat({"player_id": 5}) == 5
    assert _get_seat({"seat": 3}) == 3
    assert _get_seat({"player_seat": 7}) == 7
    assert _get_seat({}) == -1
